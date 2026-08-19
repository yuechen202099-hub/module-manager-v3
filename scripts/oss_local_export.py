#!/usr/bin/env python3
"""Download a signed OSS manifest to a Windows-local export directory.

The server-side companion writes a URL-free manifest header followed by signed
item rows to stdout.  This module consumes those rows lazily so no more than a
small bounded set of signed URLs is resident or waiting for download.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import time
import unicodedata
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook


SCHEMA = "module-manager-oss-export/v1"
RETRY_DELAYS = (1.0, 2.0, 4.0)
MAX_DOWNLOAD_WORKERS = 4
MAX_PENDING_DOWNLOADS = 8
DISK_RESERVE_BYTES = 256 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30
CHUNK_SIZE = 1024 * 1024

HEADER_FIELDS = frozenset({"schema", "kind", "planned_count", "planned_bytes"})
ITEM_FIELDS = frozenset(
    {
        "schema",
        "kind",
        "group_id",
        "photo_id",
        "category",
        "relative_path",
        "storage_bucket",
        "storage_key",
        "sha256",
        "byte_size",
        "content_type",
        "download_url",
    }
)
TABULAR_FIELDS = (
    "group_id",
    "photo_id",
    "category",
    "relative_path",
    "storage_bucket",
    "storage_key",
    "sha256",
    "byte_size",
    "content_type",
    "status",
    "downloaded_bytes",
    "error",
)
TEXT_TABULAR_FIELDS = frozenset(
    {
        "group_id",
        "photo_id",
        "category",
        "relative_path",
        "storage_bucket",
        "storage_key",
        "sha256",
        "content_type",
        "status",
        "error",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_URL_RE = re.compile(r"(?i)https?://[^\s\"'<>]+")
_SECRET_QUERY_RE = re.compile(
    r"(?i)(Signature|OSSAccessKeyId|Expires|SecurityToken|"
    r"x-oss-signature|x-oss-credential|x-oss-security-token)=([^&\s]+)"
)
_WINDOWS_INVALID_CHARS = frozenset('<>:"\\|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CLOCK$",
        "CONIN$",
        "CONOUT$",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
        *(f"COM{index}" for index in ("¹", "²", "³")),
        *(f"LPT{index}" for index in ("¹", "²", "³")),
    }
)
_LOCAL_EXPORT_OUTPUTS = frozenset(
    {
        "export-report.json",
        "manifest.csv",
        "manifest.xlsx",
        "photos.zip",
    }
)


class InsufficientDiskError(RuntimeError):
    """Raised when the destination volume cannot safely hold the export."""


def _required_string(value: Mapping[str, Any], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate or candidate != candidate.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if any(ord(character) < 32 for character in candidate):
        raise ValueError(f"{field} contains control characters")
    return candidate


def _required_positive_int(value: Mapping[str, Any], field: str) -> int:
    candidate = value.get(field)
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return candidate


def _validated_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("relative_path must be a non-empty relative path")
    if value.startswith(("/", "\\")) or _DRIVE_RE.match(value):
        raise ValueError("relative_path must not be absolute")
    if "\\" in value:
        raise ValueError("relative_path must use forward slashes")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("relative_path contains an unsafe segment")
    for segment in segments:
        if len(segment) > 255:
            raise ValueError("relative_path segment is too long")
        if segment.endswith((" ", ".")):
            raise ValueError("relative_path contains a Windows trailing alias")
        if any(ord(character) < 32 for character in segment):
            raise ValueError("relative_path contains control characters")
        if any(character in _WINDOWS_INVALID_CHARS for character in segment):
            raise ValueError("relative_path contains a Windows-invalid character")
        device_name = segment.split(".", 1)[0].rstrip(" .").upper()
        if device_name in _WINDOWS_RESERVED_NAMES:
            raise ValueError("relative_path contains a Windows reserved name")
    return value


def _collision_key(relative_path: str) -> str:
    return unicodedata.normalize("NFC", relative_path).casefold()


def _validated_download_url(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("download_url must be a non-empty HTTPS URL")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("download_url must use HTTPS")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("download_url must be a plain HTTPS signed URL")
    return value


def _validated_content_length(response: Any, expected: int) -> int:
    headers = getattr(response, "headers", None)
    if headers is None:
        raise ValueError("response Content-Length is missing")
    values: list[Any] | None = None
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = get_all("Content-Length")
    if values is None:
        get = getattr(headers, "get", None)
        raw = get("Content-Length") if callable(get) else None
        if raw is None and callable(get):
            raw = get("content-length")
        values = [] if raw is None else [raw]
    if len(values) != 1:
        raise ValueError("response Content-Length must appear exactly once")
    raw_value = values[0]
    if isinstance(raw_value, bool) or not isinstance(raw_value, (str, int)):
        raise ValueError("response Content-Length is invalid")
    text = str(raw_value).strip()
    if not text or not text.isdecimal():
        raise ValueError("response Content-Length is invalid")
    declared = int(text)
    if declared <= 0:
        raise ValueError("response Content-Length must be positive")
    if declared != expected:
        raise ValueError(
            f"byte size mismatch: expected {expected}, Content-Length declared {declared}"
        )
    return declared


@dataclass(frozen=True, slots=True)
class ManifestMetadata:
    schema: str
    kind: str
    group_id: str
    photo_id: str
    category: str
    relative_path: str
    storage_bucket: str
    storage_key: str
    sha256: str
    byte_size: int
    content_type: str


@dataclass(frozen=True, slots=True)
class ManifestItem:
    schema: str
    kind: str
    group_id: str
    photo_id: str
    category: str
    relative_path: str
    storage_bucket: str
    storage_key: str
    sha256: str
    byte_size: int
    content_type: str
    download_url: str

    def metadata(self) -> ManifestMetadata:
        return ManifestMetadata(
            schema=self.schema,
            kind=self.kind,
            group_id=self.group_id,
            photo_id=self.photo_id,
            category=self.category,
            relative_path=self.relative_path,
            storage_bucket=self.storage_bucket,
            storage_key=self.storage_key,
            sha256=self.sha256,
            byte_size=self.byte_size,
            content_type=self.content_type,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ManifestItem":
        if not isinstance(value, Mapping) or frozenset(value.keys()) != ITEM_FIELDS:
            raise ValueError("manifest item fields do not match the required schema")
        if value.get("schema") != SCHEMA:
            raise ValueError("manifest item schema is unsupported")
        if value.get("kind") != "item":
            raise ValueError("manifest item kind must be item")
        sha256 = value.get("sha256")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        relative_path = _validated_relative_path(_required_string(value, "relative_path"))
        return cls(
            schema=SCHEMA,
            kind="item",
            group_id=_required_string(value, "group_id"),
            photo_id=_required_string(value, "photo_id"),
            category=_required_string(value, "category"),
            relative_path=relative_path,
            storage_bucket=_required_string(value, "storage_bucket"),
            storage_key=_required_string(value, "storage_key"),
            sha256=sha256.lower(),
            byte_size=_required_positive_int(value, "byte_size"),
            content_type=_required_string(value, "content_type"),
            download_url=_validated_download_url(value.get("download_url")),
        )


@dataclass(frozen=True, slots=True)
class ItemResult:
    item: ManifestMetadata
    succeeded: bool
    local_path: str | None
    downloaded_bytes: int
    actual_sha256: str | None
    error: str | None

    @classmethod
    def success(cls, item: ManifestItem, target: Path, size: int) -> "ItemResult":
        return cls(
            item=item.metadata(),
            succeeded=True,
            local_path=str(target.resolve()),
            downloaded_bytes=size,
            actual_sha256=item.sha256,
            error=None,
        )

    @classmethod
    def failure(cls, item: ManifestItem, error: str) -> "ItemResult":
        return cls(
            item=item.metadata(),
            succeeded=False,
            local_path=None,
            downloaded_bytes=0,
            actual_sha256=None,
            error=error,
        )


@dataclass(frozen=True, slots=True)
class ExportReport:
    items: tuple[ManifestMetadata, ...]
    results: tuple[ItemResult, ...]
    planned_bytes: int
    output_root: Path
    generated_at: str

    @property
    def planned(self) -> int:
        return len(self.items)

    @property
    def succeeded(self) -> int:
        return sum(result.succeeded for result in self.results)

    @property
    def failed(self) -> int:
        return self.planned - self.succeeded

    @property
    def downloaded_bytes(self) -> int:
        return sum(result.downloaded_bytes for result in self.results)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _path_is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _assert_no_link_or_reparse_ancestors(path: Path) -> None:
    absolute = _lexical_absolute(path)
    parts = absolute.parts
    if not parts:
        raise ValueError("output root must be an absolute path")
    current = Path(parts[0])
    if _path_is_link_or_reparse(current):
        raise ValueError("output root ancestor is a symlink or reparse point")
    for segment in parts[1:]:
        current /= segment
        if _path_is_link_or_reparse(current):
            raise ValueError("output root ancestor is a symlink or reparse point")


def _assert_no_link_or_reparse_components(output_root: Path, target: Path) -> None:
    root = _lexical_absolute(output_root)
    candidate = _lexical_absolute(target)
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("relative_path escapes the output root") from exc
    _assert_no_link_or_reparse_ancestors(root)
    current = root
    for segment in relative.parts:
        current /= segment
        if _path_is_link_or_reparse(current):
            raise ValueError("relative_path contains a symlink or reparse point")


def _assert_safe_download_paths(output_root: Path, target: Path, part: Path) -> None:
    _assert_no_link_or_reparse_components(output_root, target)
    _assert_no_link_or_reparse_components(output_root, part)


def safe_output_path(output_root: Path, relative_path: str) -> Path:
    """Return a path beneath output_root after platform-independent validation."""
    safe_relative_path = _validated_relative_path(relative_path)
    root = _lexical_absolute(output_root)
    target = root / Path(*safe_relative_path.split("/"))
    _assert_no_link_or_reparse_components(root, target)
    return target


def sanitize_error(error: BaseException | str) -> str:
    """Return a single-line diagnostic that cannot retain a signed URL."""
    if isinstance(error, HTTPError):
        raw = f"HTTP {error.code}: {error.reason}"
    elif isinstance(error, URLError):
        raw = f"URL error: {error.reason}"
    else:
        raw = str(error) or type(error).__name__
    sanitized = raw.replace("\r", " ").replace("\n", " ")
    sanitized = _URL_RE.sub("[redacted-url]", sanitized)
    sanitized = _SECRET_QUERY_RE.sub("[redacted-query]", sanitized)
    sanitized = re.sub(r"(?i)download_url", "signed request", sanitized)
    return sanitized[:1000]


def _download_one(
    item: ManifestItem,
    output_root: Path,
    *,
    opener: Callable[..., Any],
    sleeper: Callable[[float], None],
    retry_delays: tuple[float, ...],
) -> ItemResult:
    try:
        target = safe_output_path(output_root, item.relative_path)
        part = target.with_name(target.name + ".part")
    except Exception as exc:
        return ItemResult.failure(item, sanitize_error(exc))
    for attempt in range(len(retry_delays) + 1):
        try:
            _assert_safe_download_paths(output_root, target, part)
            cleanup_error = _cleanup_part(part)
            if cleanup_error:
                raise RuntimeError(f"temporary file cleanup failed: {cleanup_error}")
            target.parent.mkdir(parents=True, exist_ok=True)
            _assert_safe_download_paths(output_root, target, part)
            digest = hashlib.sha256()
            size = 0
            with opener(item.download_url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                _validated_content_length(response, item.byte_size)
                with part.open("xb") as output:
                    while size < item.byte_size:
                        remaining = item.byte_size - size
                        chunk = response.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        if not isinstance(chunk, bytes):
                            raise ValueError("download response returned non-byte content")
                        next_size = size + len(chunk)
                        if next_size > item.byte_size:
                            raise ValueError(
                                "download response exceeds declared byte_size"
                            )
                        output.write(chunk)
                        digest.update(chunk)
                        size = next_size
                    output.flush()
                    os.fsync(output.fileno())
            if size != item.byte_size:
                raise ValueError(
                    f"byte size mismatch: expected {item.byte_size}, observed {size}"
                )
            observed_sha256 = digest.hexdigest()
            if observed_sha256 != item.sha256:
                raise ValueError("sha256 mismatch")
            _assert_safe_download_paths(output_root, target, part)
            os.replace(part, target)
            return ItemResult.success(item, target, size)
        except Exception as exc:
            error = sanitize_error(exc)
            cleanup_error = _cleanup_part(part)
            if cleanup_error:
                error = f"{error}; temporary file cleanup failed: {cleanup_error}"
            if cleanup_error or attempt == len(retry_delays):
                return ItemResult.failure(item, error)
            sleeper(retry_delays[attempt])
    raise AssertionError("unreachable")


def _cleanup_part(part: Path) -> str | None:
    try:
        if _path_is_link_or_reparse(part):
            return "temporary path is a symlink or reparse point"
        part.unlink(missing_ok=True)
    except Exception as exc:
        return sanitize_error(exc)
    return None


def download_manifest(
    items: Iterable[ManifestItem],
    output_root: Path,
    max_workers: int = 4,
    retry_delays: tuple[float, ...] = RETRY_DELAYS,
    *,
    opener: Callable[..., Any] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
    max_pending: int = MAX_PENDING_DOWNLOADS,
) -> ExportReport:
    """Download items with stable results and bounded submission/backpressure."""
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or not 1 <= max_workers <= MAX_DOWNLOAD_WORKERS
    ):
        raise ValueError("max_workers must be between 1 and 4")
    if (
        isinstance(max_pending, bool)
        or not isinstance(max_pending, int)
        or not 1 <= max_pending <= MAX_PENDING_DOWNLOADS
    ):
        raise ValueError("max_pending must be between 1 and 8")
    if not isinstance(retry_delays, tuple) or any(
        isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0
        for delay in retry_delays
    ):
        raise ValueError("retry_delays must be a tuple of non-negative numbers")

    iterator = iter(items)
    submitted_items: list[ManifestMetadata] = []
    results_by_index: dict[int, ItemResult] = {}
    used_runtime_paths: set[str] = {
        _collision_key(path)
        for output_name in _LOCAL_EXPORT_OUTPUTS
        for path in (output_name, output_name + ".part")
    }
    pending: dict[Future[ItemResult], int] = {}
    exhausted = False

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while not exhausted or pending:
            while not exhausted and len(pending) < max_pending:
                try:
                    item = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                if not isinstance(item, ManifestItem):
                    raise ValueError("items must contain ManifestItem values")
                safe_output_path(output_root, item.relative_path)
                final_key = _collision_key(item.relative_path)
                part_key = _collision_key(item.relative_path + ".part")
                if any(
                    final_key == used_path
                    or final_key.startswith(used_path + "/")
                    or used_path.startswith(final_key + "/")
                    or part_key == used_path
                    or part_key.startswith(used_path + "/")
                    or used_path.startswith(part_key + "/")
                    for used_path in used_runtime_paths
                ):
                    raise ValueError(
                        "duplicate relative_path or reserved runtime path is not allowed: "
                        f"{item.relative_path}"
                    )
                used_runtime_paths.update((final_key, part_key))
                index = len(submitted_items)
                submitted_items.append(item.metadata())
                future = executor.submit(
                    _download_one,
                    item,
                    output_root,
                    opener=opener,
                    sleeper=sleeper,
                    retry_delays=retry_delays,
                )
                pending[future] = index
                del item
            if not pending:
                continue
            completed, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in completed:
                index = pending.pop(future)
                results_by_index[index] = future.result()

    ordered_results = tuple(
        results_by_index[index] for index in range(len(submitted_items))
    )
    return ExportReport(
        items=tuple(submitted_items),
        results=ordered_results,
        planned_bytes=sum(item.byte_size for item in submitted_items),
        output_root=output_root.resolve(strict=False),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_json_object(line: str, *, context: str) -> Mapping[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(line, object_pairs_hook=unique_object)
    except ValueError as exc:
        if "duplicate JSON key:" in str(exc):
            raise ValueError(f"{context} contains {exc}") from exc
        raise ValueError(f"{context} must be valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _parse_header(input_stream: TextIO) -> tuple[int, int]:
    first_line = input_stream.readline()
    if not first_line or not first_line.strip():
        raise ValueError("manifest header must be the first line")
    header = _parse_json_object(first_line, context="manifest header")
    if frozenset(header.keys()) != HEADER_FIELDS:
        raise ValueError("manifest header fields do not match the required schema")
    if header.get("schema") != SCHEMA or header.get("kind") != "manifest":
        raise ValueError("manifest header schema or kind is invalid")
    planned_count = header.get("planned_count")
    planned_bytes = header.get("planned_bytes")
    if (
        isinstance(planned_count, bool)
        or not isinstance(planned_count, int)
        or planned_count < 0
    ):
        raise ValueError("manifest header planned_count must be a non-negative integer")
    if (
        isinstance(planned_bytes, bool)
        or not isinstance(planned_bytes, int)
        or planned_bytes < 0
    ):
        raise ValueError("manifest header planned_bytes must be a non-negative integer")
    return planned_count, planned_bytes


def _iter_stream_items(
    input_stream: TextIO, *, planned_count: int, planned_bytes: int
) -> Iterator[ManifestItem]:
    observed_count = 0
    observed_bytes = 0
    for line_number, line in enumerate(input_stream, start=2):
        if not line.strip():
            raise ValueError(f"manifest item line {line_number} must not be blank")
        value = _parse_json_object(line, context=f"manifest item line {line_number}")
        if value.get("kind") == "manifest":
            raise ValueError("manifest header must be unique and appear only first")
        item = ManifestItem.from_mapping(value)
        observed_count += 1
        observed_bytes += item.byte_size
        yield item
    if observed_count != planned_count:
        raise ValueError(
            f"manifest item count mismatch: expected {planned_count}, observed {observed_count}"
        )
    if observed_bytes != planned_bytes:
        raise ValueError(
            f"manifest bytes total mismatch: expected {planned_bytes}, observed {observed_bytes}"
        )


def _existing_disk_probe(path: Path) -> Path:
    probe = path.resolve(strict=False)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def _check_disk_space(output_root: Path, planned_bytes: int, formats: set[str]) -> None:
    required = planned_bytes
    if "zip" in formats:
        required += planned_bytes
    required += max(planned_bytes // 10, DISK_RESERVE_BYTES)
    free = shutil.disk_usage(_existing_disk_probe(output_root)).free
    if free < required:
        raise InsufficientDiskError(
            f"insufficient disk space: required {required} bytes, available {free} bytes"
        )


def _sanitized_row(result: ItemResult) -> dict[str, Any]:
    item = result.item
    row = {
        "group_id": item.group_id,
        "photo_id": item.photo_id,
        "category": item.category,
        "relative_path": item.relative_path,
        "storage_bucket": item.storage_bucket,
        "storage_key": item.storage_key,
        "sha256": item.sha256,
        "byte_size": item.byte_size,
        "content_type": item.content_type,
        "status": "succeeded" if result.succeeded else "failed",
        "downloaded_bytes": result.downloaded_bytes,
        "error": result.error or "",
    }
    return {
        key: _sanitize_artifact_text(value) if isinstance(value, str) else value
        for key, value in row.items()
    }


def _sanitize_artifact_text(value: str) -> str:
    sanitized = "".join(" " if ord(character) < 32 else character for character in value)
    sanitized = _URL_RE.sub("[redacted-url]", sanitized)
    return _SECRET_QUERY_RE.sub("[redacted-query]", sanitized)


def _spreadsheet_text(value: Any) -> Any:
    if isinstance(value, str):
        first_meaningful = value.lstrip()
        if first_meaningful.startswith(("=", "+", "-", "@")):
            return "'" + value
    return value


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _prepare_atomic_artifact(target: Path) -> Path:
    part = target.with_name(target.name + ".part")
    _assert_safe_download_paths(target.parent, target, part)
    cleanup_error = _cleanup_part(part)
    if cleanup_error:
        raise ValueError(f"temporary artifact cleanup failed: {cleanup_error}")
    _assert_safe_download_paths(target.parent, target, part)
    return part


def _replace_atomic_artifact(part: Path, target: Path) -> None:
    _assert_safe_download_paths(target.parent, target, part)
    os.replace(part, target)


def _atomic_csv(report: ExportReport, target: Path) -> None:
    part = _prepare_atomic_artifact(target)
    try:
        with part.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TABULAR_FIELDS)
            writer.writeheader()
            for result in report.results:
                writer.writerow(
                    {
                        key: _spreadsheet_text(value)
                        for key, value in _sanitized_row(result).items()
                    }
                )
            handle.flush()
            os.fsync(handle.fileno())
        _replace_atomic_artifact(part, target)
    finally:
        _cleanup_part(part)


def _format_sheet(sheet: Any, headers: Sequence[str], row_count: int) -> None:
    sheet.freeze_panes = "A2"
    last_column = sheet.cell(row=1, column=len(headers)).column_letter
    sheet.auto_filter.ref = f"A1:{last_column}{max(row_count + 1, 1)}"
    for column_index, header in enumerate(headers, start=1):
        if header in TEXT_TABULAR_FIELDS:
            for row_index in range(2, row_count + 2):
                sheet.cell(row=row_index, column=column_index).number_format = "@"


def _atomic_xlsx(report: ExportReport, target: Path) -> None:
    part = _prepare_atomic_artifact(target)
    try:
        workbook = Workbook()
        manifest_sheet = workbook.active
        manifest_sheet.title = "Manifest"
        manifest_sheet.append(list(TABULAR_FIELDS))
        rows = [_sanitized_row(result) for result in report.results]
        for row in rows:
            manifest_sheet.append([_spreadsheet_text(row[field]) for field in TABULAR_FIELDS])
        _format_sheet(manifest_sheet, TABULAR_FIELDS, len(rows))

        failure_headers = (
            "group_id",
            "photo_id",
            "relative_path",
            "storage_key",
            "sha256",
            "byte_size",
            "error",
        )
        failures = [row for row in rows if row["status"] == "failed"]
        failure_sheet = workbook.create_sheet("Failures")
        failure_sheet.append(list(failure_headers))
        for row in failures:
            failure_sheet.append(
                [_spreadsheet_text(row[field]) for field in failure_headers]
            )
        _format_sheet(failure_sheet, failure_headers, len(failures))
        with part.open("xb") as handle:
            workbook.save(handle)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_atomic_artifact(part, target)
    finally:
        _cleanup_part(part)


def _zip_source_lstat(path: Path) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ValueError("ZIP source changed or is unavailable") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise ValueError("ZIP source is a symlink, reparse point, or unsafe file")
    return metadata


def _zip_source_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _write_verified_zip_entry(
    archive: ZipFile,
    report: ExportReport,
    result: ItemResult,
) -> None:
    if not result.local_path:
        raise ValueError("ZIP source path is missing")
    source = _lexical_absolute(Path(result.local_path))
    expected_source = safe_output_path(report.output_root, result.item.relative_path)
    if source != expected_source:
        raise ValueError("ZIP source path changed")

    _assert_no_link_or_reparse_components(report.output_root, source)
    before_open = _zip_source_lstat(source)
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("ZIP source is not a regular file")
        opened_identity = _zip_source_identity(opened)
        if _zip_source_identity(before_open) != opened_identity:
            raise ValueError("ZIP source identity changed while opening")
        if opened.st_size != result.item.byte_size:
            raise ValueError("ZIP source size changed before streaming")

        _assert_no_link_or_reparse_components(report.output_root, source)
        after_open = _zip_source_lstat(source)
        if _zip_source_identity(after_open) != opened_identity:
            raise ValueError("ZIP source identity changed after opening")

        source_handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with source_handle:
            digest = hashlib.sha256()
            observed_size = 0
            with archive.open(
                result.item.relative_path,
                mode="w",
                force_zip64=True,
            ) as archive_entry:
                while True:
                    remaining = result.item.byte_size - observed_size
                    chunk = source_handle.read(min(CHUNK_SIZE, remaining + 1))
                    if not chunk:
                        break
                    next_size = observed_size + len(chunk)
                    if next_size > result.item.byte_size:
                        raise ValueError("ZIP source size changed while streaming")
                    archive_entry.write(chunk)
                    digest.update(chunk)
                    observed_size = next_size

            after_stream = os.fstat(source_handle.fileno())
            if (
                not stat.S_ISREG(after_stream.st_mode)
                or _zip_source_identity(after_stream) != opened_identity
                or after_stream.st_size != opened.st_size
            ):
                raise ValueError("ZIP source descriptor changed while streaming")

            _assert_no_link_or_reparse_components(report.output_root, source)
            current = _zip_source_lstat(source)
            if (
                _zip_source_identity(current) != opened_identity
                or current.st_size != after_stream.st_size
            ):
                raise ValueError("ZIP source path changed while streaming")
            if observed_size != result.item.byte_size:
                raise ValueError("ZIP source size changed while streaming")
            if digest.hexdigest() != result.item.sha256:
                raise ValueError("ZIP source sha256 changed after download verification")
    except OSError as exc:
        raise ValueError("ZIP source changed or is unsafe") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_zip(report: ExportReport, target: Path) -> None:
    part = _prepare_atomic_artifact(target)
    try:
        with ZipFile(part, mode="x", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for result in report.results:
                if not result.succeeded or not result.local_path:
                    continue
                _write_verified_zip_entry(archive, report, result)
        _fsync_file(part)
        _replace_atomic_artifact(part, target)
    finally:
        _cleanup_part(part)


def _atomic_report(report: ExportReport, target: Path) -> None:
    payload = {
        "schema": "module-manager-local-export-report/v1",
        "generated_at": report.generated_at,
        "output_root": str(report.output_root),
        "planned": report.planned,
        "planned_bytes": report.planned_bytes,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "downloaded_bytes": report.downloaded_bytes,
        "complete": report.failed == 0,
        "items": [_sanitized_row(result) for result in report.results],
    }
    part = _prepare_atomic_artifact(target)
    try:
        with part.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _replace_atomic_artifact(part, target)
    finally:
        _cleanup_part(part)


def _validated_formats(formats: set[str] | None) -> set[str]:
    normalized = {"files"} if formats is None else set(formats)
    unknown = normalized - {"files", "zip", "csv", "xlsx"}
    if unknown:
        raise ValueError(f"unsupported export formats: {', '.join(sorted(unknown))}")
    return normalized


def run_export_stream(
    input_stream: TextIO,
    output_root: Path,
    formats: set[str] | None = None,
    *,
    max_workers: int = 4,
    opener: Callable[..., Any] = urlopen,
) -> ExportReport:
    """Consume the manifest header eagerly and item lines only under backpressure."""
    selected_formats = _validated_formats(formats)
    planned_count, planned_bytes = _parse_header(input_stream)
    _assert_no_link_or_reparse_components(output_root, output_root)
    _check_disk_space(output_root, planned_bytes, selected_formats)
    item_iterator = _iter_stream_items(
        input_stream,
        planned_count=planned_count,
        planned_bytes=planned_bytes,
    )
    report = download_manifest(
        item_iterator,
        output_root,
        max_workers=max_workers,
        retry_delays=RETRY_DELAYS,
        opener=opener,
        max_pending=MAX_PENDING_DOWNLOADS,
    )
    # The lazy iterator reconciles these values at EOF before this point.
    if report.planned != planned_count or report.planned_bytes != planned_bytes:
        raise ValueError("manifest preflight totals do not match downloaded items")

    _assert_no_link_or_reparse_components(output_root, output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    _assert_no_link_or_reparse_components(output_root, output_root)
    if "zip" in selected_formats:
        _atomic_zip(report, output_root / "photos.zip")
    if "csv" in selected_formats:
        _atomic_csv(report, output_root / "manifest.csv")
    if "xlsx" in selected_formats:
        _atomic_xlsx(report, output_root / "manifest.xlsx")
    _atomic_report(report, output_root / "export-report.json")
    return report


def run_export(
    stdin_text: str,
    output_root: Path,
    formats: set[str] | None = None,
    *,
    max_workers: int = 4,
    opener: Callable[..., Any] = urlopen,
) -> ExportReport:
    return run_export_stream(
        io.StringIO(stdin_text),
        output_root,
        formats,
        max_workers=max_workers,
        opener=opener,
    )


def _default_output_root() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "Downloads" / "module-manager-exports" / stamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a streamed OSS export manifest to this computer."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=("files", "zip", "csv", "xlsx"),
    )
    parser.add_argument(
        "--max-workers", type=int, choices=range(1, MAX_DOWNLOAD_WORKERS + 1), default=4
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output is None:
        displayed_output_root = _default_output_root()
        output_root = displayed_output_root.resolve(strict=False)
    else:
        displayed_output_root = None
        output_root = args.output
    formats = set(args.formats) if args.formats else None
    try:
        report = run_export_stream(
            sys.stdin,
            output_root,
            formats,
            max_workers=args.max_workers,
        )
    except Exception as exc:
        print(f"local export preflight failed: {sanitize_error(exc)}", file=sys.stderr)
        return 3
    print(
        json.dumps(
            {
                "output_root": str(
                    displayed_output_root
                    if displayed_output_root is not None
                    else report.output_root
                ),
                "planned": report.planned,
                "succeeded": report.succeeded,
                "failed": report.failed,
            },
            ensure_ascii=False,
        )
    )
    return 2 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
