from __future__ import annotations

import hashlib
import io
import json
import shutil
import threading
import time
from collections import namedtuple
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

import scripts.oss_local_export as exporter
from scripts.oss_local_export import (
    MAX_PENDING_DOWNLOADS,
    ExportReport,
    InsufficientDiskError,
    ManifestItem,
    download_manifest,
    run_export,
    run_export_stream,
    sanitize_error,
)


IMAGE_BYTES = b"verified-fake-oss-image"
IMAGE_SHA256 = hashlib.sha256(IMAGE_BYTES).hexdigest()
SCHEMA = "module-manager-oss-export/v1"


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class FakeHttpClient:
    def __init__(self, outcomes: Iterable[bytes | BaseException]) -> None:
        self.outcomes = iter(outcomes)
        self.sleeps: list[float] = []
        self.urls: list[str] = []

    def open(self, url: str, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        self.urls.append(url)
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)


def valid_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "item",
        "group_id": "group-001",
        "photo_id": "000123456789",
        "category": "现场照片",
        "relative_path": "T01/group-001/现场照片/photo-001.jpg",
        "storage_bucket": "photos-read-only",
        "storage_key": "photos/aa/object.jpg",
        "sha256": IMAGE_SHA256,
        "byte_size": len(IMAGE_BYTES),
        "content_type": "image/jpeg",
        "download_url": "https://oss.example.invalid/photos/aa/object.jpg?Expires=1&Signature=secret",
    }
    row.update(overrides)
    return row


def manifest_item(**overrides: Any) -> ManifestItem:
    return ManifestItem.from_mapping(valid_row(**overrides))


def manifest_jsonl(count: int, *, byte_size: int | None = None) -> str:
    item_size = len(IMAGE_BYTES) if byte_size is None else byte_size
    rows: list[dict[str, Any]] = [
        {
            "schema": SCHEMA,
            "kind": "manifest",
            "planned_count": count,
            "planned_bytes": count * item_size,
        }
    ]
    for index in range(count):
        rows.append(
            valid_row(
                group_id=f"group-{index:03d}",
                photo_id=f"{index:012d}",
                relative_path=f"T01/group-{index:03d}/photo-{index:03d}.jpg",
                storage_key=f"photos/{index:03d}.jpg",
                byte_size=item_size,
                download_url=(
                    f"https://oss.example.invalid/photos/{index:03d}.jpg"
                    f"?Expires=1&Signature=secret-{index}"
                ),
            )
        )
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def fake_oss_opener(_url: str, *, timeout: int) -> FakeResponse:
    assert timeout == 30
    return FakeResponse(IMAGE_BYTES)


@pytest.mark.parametrize(
    "relative_path",
    [
        "../escape.jpg",
        "/absolute.jpg",
        "C:/absolute.jpg",
        "\\\\server\\share\\photo.jpg",
        "safe/..\\escape.jpg",
        "safe//photo.jpg",
        "safe/./photo.jpg",
        "safe/NUL.jpg",
        "safe/com1.png",
        "safe/trailing. /photo.jpg",
        "safe/photo?.jpg",
    ],
)
def test_manifest_rejects_unsafe_windows_relative_paths(relative_path: str) -> None:
    """Removing a Windows path guard must allow one of these escape/alias paths."""
    with pytest.raises(ValueError, match="relative_path"):
        ManifestItem.from_mapping(valid_row(relative_path=relative_path))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"sha256": "not-a-hash"}, "sha256"),
        ({"byte_size": 0}, "byte_size"),
        ({"byte_size": True}, "byte_size"),
        ({"download_url": "http://oss.invalid/photo.jpg"}, "HTTPS"),
        ({"schema": "module-manager-oss-export/v2"}, "schema"),
        ({"kind": "manifest"}, "kind"),
        ({"group_id": ""}, "group_id"),
        ({"storage_key": ""}, "storage_key"),
    ],
)
def test_manifest_item_strictly_validates_required_fields(
    updates: dict[str, Any], message: str
) -> None:
    """Weakening a required field check must admit a malformed download request."""
    with pytest.raises(ValueError, match=message):
        ManifestItem.from_mapping(valid_row(**updates))


def test_manifest_item_rejects_missing_or_unknown_fields() -> None:
    """Changing the fixed item schema must not be silently accepted."""
    missing = valid_row()
    missing.pop("photo_id")
    with pytest.raises(ValueError, match="fields"):
        ManifestItem.from_mapping(missing)
    with pytest.raises(ValueError, match="fields"):
        ManifestItem.from_mapping(valid_row(unexpected="value"))


def test_download_retries_to_part_then_atomically_replaces(tmp_path: Path) -> None:
    """Removing retry or atomic replacement must leave the target absent/partial."""
    client = FakeHttpClient([TimeoutError(), TimeoutError(), IMAGE_BYTES])
    report = download_manifest(
        [manifest_item()],
        tmp_path,
        max_workers=1,
        retry_delays=(1.0, 2.0, 4.0),
        opener=client.open,
        sleeper=client.sleep,
    )
    target = tmp_path / manifest_item().relative_path
    assert target.read_bytes() == IMAGE_BYTES
    assert not target.with_name(target.name + ".part").exists()
    assert client.sleeps == [1.0, 2.0]
    assert report.succeeded == 1
    assert report.failed == 0


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [(b"wrong-size", "byte size mismatch"), (b"verified-fake-oss-imagf", "sha256 mismatch")],
)
def test_verification_failure_keeps_no_final_or_part_file(
    tmp_path: Path, payload: bytes, expected_error: str
) -> None:
    """Removing size/hash verification must publish corrupt bytes as successful."""
    item = manifest_item()
    report = download_manifest(
        [item],
        tmp_path,
        max_workers=1,
        retry_delays=(),
        opener=lambda *_a, **_k: FakeResponse(payload),
    )
    target = tmp_path / item.relative_path
    assert report.failed == 1
    assert expected_error in (report.results[0].error or "")
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_expired_signature_is_retried_and_error_is_sanitized(tmp_path: Path) -> None:
    """Leaking the HTTPError URL must expose its Signature in result/report output."""
    url = valid_row()["download_url"]
    error = HTTPError(url, 403, "Signature expired", {}, None)
    client = FakeHttpClient([error, error])
    report = download_manifest(
        [manifest_item()],
        tmp_path,
        max_workers=1,
        retry_delays=(1.0,),
        opener=client.open,
        sleeper=client.sleep,
    )
    assert report.failed == 1
    assert client.sleeps == [1.0]
    assert report.results[0].error == "HTTP 403: Signature expired"
    assert "https://" not in report.results[0].error
    assert "Signature=" not in report.results[0].error


def test_error_sanitizer_removes_bare_signature_query_fragments() -> None:
    """Redacting only the value must still leave a forbidden Signature= query marker."""
    message = sanitize_error(
        RuntimeError("request failed: Signature=top-secret&OSSAccessKeyId=key-secret")
    )
    assert "Signature=" not in message
    assert "OSSAccessKeyId=" not in message
    assert "top-secret" not in message
    assert "key-secret" not in message


@pytest.mark.parametrize("max_workers", [0, 5, -1, 1.5, "4", True])
def test_download_manifest_rejects_workers_outside_one_to_four(
    tmp_path: Path, max_workers: Any
) -> None:
    """Removing the worker limit must permit unsafe local/OSS concurrency."""
    with pytest.raises(ValueError, match="max_workers"):
        download_manifest([], tmp_path, max_workers=max_workers)


@pytest.mark.parametrize("max_pending", [0, 9, -1, 1.5, "8", True])
def test_download_manifest_rejects_pending_bound_outside_one_to_eight(
    tmp_path: Path, max_pending: Any
) -> None:
    """Removing the pending limit must permit unbounded signed-URL accumulation."""
    with pytest.raises(ValueError, match="max_pending"):
        download_manifest([], tmp_path, max_pending=max_pending)


def test_duplicate_and_case_colliding_output_paths_are_rejected(tmp_path: Path) -> None:
    """Removing canonical collision checks must let two items overwrite one Windows file."""
    exact = [manifest_item(), manifest_item(photo_id="2", storage_key="other")]
    with pytest.raises(ValueError, match="duplicate relative_path"):
        download_manifest(exact, tmp_path, max_workers=1, retry_delays=(), opener=fake_oss_opener)

    case_collision = [
        manifest_item(relative_path="T01/Folder/Photo.jpg"),
        manifest_item(
            photo_id="2",
            storage_key="other",
            relative_path="t01/folder/photo.JPG",
        ),
    ]
    with pytest.raises(ValueError, match="duplicate relative_path"):
        download_manifest(
            case_collision,
            tmp_path / "case",
            max_workers=1,
            retry_delays=(),
            opener=fake_oss_opener,
        )


@pytest.mark.parametrize(
    "relative_paths",
    [
        ("folder/photo.jpg", "folder/photo.jpg.part"),
        ("export-report.json",),
        ("photos.zip.part",),
    ],
)
def test_runtime_part_and_composer_output_collisions_are_rejected(
    tmp_path: Path, relative_paths: tuple[str, ...]
) -> None:
    """Ignoring runtime outputs must let a download overwrite a part/report artifact."""
    items = [
        manifest_item(
            group_id=str(index),
            photo_id=str(index),
            relative_path=relative_path,
            storage_key=f"p/{index}.jpg",
        )
        for index, relative_path in enumerate(relative_paths)
    ]
    with pytest.raises(ValueError, match="relative_path"):
        download_manifest(
            items,
            tmp_path,
            max_workers=1,
            retry_delays=(),
            opener=fake_oss_opener,
        )


def test_results_remain_in_manifest_order_and_partial_success_is_preserved(
    tmp_path: Path,
) -> None:
    """Recording completion order must make reports unstable across runs."""
    lock = threading.Lock()
    attempts: dict[str, int] = {}

    def opener(url: str, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        with lock:
            attempts[url] = attempts.get(url, 0) + 1
        if "001.jpg" in url:
            raise TimeoutError("signed request timed out")
        if "000.jpg" in url:
            time.sleep(0.03)
        return FakeResponse(IMAGE_BYTES)

    items = [
        manifest_item(
            group_id=f"g-{i}",
            photo_id=str(i),
            relative_path=f"g-{i}/photo.jpg",
            storage_key=f"photos/{i:03d}.jpg",
            download_url=f"https://oss.invalid/{i:03d}.jpg?Signature=secret",
        )
        for i in range(3)
    ]
    report = download_manifest(
        items,
        tmp_path,
        max_workers=3,
        retry_delays=(),
        opener=opener,
    )
    assert [result.item.photo_id for result in report.results] == ["0", "1", "2"]
    assert report.succeeded == 2
    assert report.failed == 1
    assert (tmp_path / "g-0/photo.jpg").read_bytes() == IMAGE_BYTES
    assert not (tmp_path / "g-1/photo.jpg").exists()
    assert (tmp_path / "g-2/photo.jpg").read_bytes() == IMAGE_BYTES


def test_concurrency_never_exceeds_four(tmp_path: Path) -> None:
    """Using more executor workers than allowed must raise observed concurrency above four."""
    lock = threading.Lock()
    active = 0
    peak = 0

    def opener(_url: str, *, timeout: int) -> FakeResponse:
        nonlocal active, peak
        assert timeout == 30
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return FakeResponse(IMAGE_BYTES)

    items = [
        manifest_item(
            group_id=str(i),
            photo_id=str(i),
            relative_path=f"g{i}/p.jpg",
            storage_key=f"p/{i}.jpg",
            download_url=f"https://oss.invalid/{i}?Signature=secret",
        )
        for i in range(20)
    ]
    report = download_manifest(items, tmp_path, max_workers=4, opener=opener)
    assert report.succeeded == 20
    assert 2 <= peak <= 4


def test_pending_futures_bound_applies_backpressure_to_lazy_items(tmp_path: Path) -> None:
    """Eagerly collecting items must consume more than eight signed URLs before progress."""
    release = threading.Event()
    started = threading.Event()
    consumed = 0
    consumed_lock = threading.Lock()

    def items() -> Iterable[ManifestItem]:
        nonlocal consumed
        for i in range(20):
            with consumed_lock:
                consumed += 1
            yield manifest_item(
                group_id=str(i),
                photo_id=str(i),
                relative_path=f"g{i}/p.jpg",
                storage_key=f"p/{i}.jpg",
                download_url=f"https://oss.invalid/{i}?Signature=secret",
            )

    def opener(_url: str, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        started.set()
        assert release.wait(timeout=5)
        return FakeResponse(IMAGE_BYTES)

    outcome: list[ExportReport] = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            download_manifest(items(), tmp_path, max_workers=4, opener=opener)
        )
    )
    worker.start()
    assert started.wait(timeout=2)
    time.sleep(0.05)
    with consumed_lock:
        assert consumed == MAX_PENDING_DOWNLOADS == 8
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert outcome[0].succeeded == 20


@pytest.mark.parametrize(
    "text",
    [
        "",
        json.dumps(valid_row()) + "\n",
        json.dumps({"schema": SCHEMA, "kind": "manifest", "planned_count": 0}) + "\n",
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": "manifest",
                "planned_count": 0,
                "planned_bytes": 0,
                "download_url": "https://forbidden.invalid/?Signature=secret",
            }
        )
        + "\n",
    ],
)
def test_stream_requires_exact_url_free_header_first(tmp_path: Path, text: str) -> None:
    """Weak header validation must admit missing fields, items first, or signed URLs."""
    with pytest.raises(ValueError, match="header"):
        run_export_stream(io.StringIO(text), tmp_path, opener=fake_oss_opener)


def test_stream_rejects_duplicate_or_late_header(tmp_path: Path) -> None:
    """Treating a later manifest row as an item must allow ambiguous stream boundaries."""
    header = {
        "schema": SCHEMA,
        "kind": "manifest",
        "planned_count": 1,
        "planned_bytes": len(IMAGE_BYTES),
    }
    text = json.dumps(header) + "\n" + json.dumps(header) + "\n"
    with pytest.raises(ValueError, match="header"):
        run_export_stream(io.StringIO(text), tmp_path, opener=fake_oss_opener)


@pytest.mark.parametrize(
    ("planned_count", "planned_bytes", "message"),
    [(2, len(IMAGE_BYTES), "count"), (1, len(IMAGE_BYTES) + 1, "bytes")],
)
def test_stream_rejects_eof_count_or_byte_total_mismatch(
    tmp_path: Path, planned_count: int, planned_bytes: int, message: str
) -> None:
    """Skipping the EOF reconciliation must report an incomplete manifest as complete."""
    rows = [
        {
            "schema": SCHEMA,
            "kind": "manifest",
            "planned_count": planned_count,
            "planned_bytes": planned_bytes,
        },
        valid_row(),
    ]
    text = "".join(json.dumps(row) + "\n" for row in rows)
    with pytest.raises(ValueError, match=message):
        run_export_stream(io.StringIO(text), tmp_path, opener=fake_oss_opener)
    assert not (tmp_path / "export-report.json").exists()
    assert not (tmp_path / "photos.zip").exists()


def test_stream_consumes_only_bounded_item_lines_before_download_progress(
    tmp_path: Path,
) -> None:
    """Calling read/readlines must collect every signed URL before any download begins."""
    header = {
        "schema": SCHEMA,
        "kind": "manifest",
        "planned_count": 20,
        "planned_bytes": 20 * len(IMAGE_BYTES),
    }
    lines = [json.dumps(header) + "\n"] + [
        json.dumps(
            valid_row(
                group_id=str(i),
                photo_id=str(i),
                relative_path=f"g{i}/p.jpg",
                storage_key=f"p/{i}.jpg",
                download_url=f"https://oss.invalid/{i}?Signature=secret",
            )
        )
        + "\n"
        for i in range(20)
    ]

    class TrackingStream:
        def __init__(self) -> None:
            self.index = 0
            self.lock = threading.Lock()

        def readline(self) -> str:
            with self.lock:
                if self.index == len(lines):
                    return ""
                line = lines[self.index]
                self.index += 1
                return line

        def __iter__(self) -> "TrackingStream":
            return self

        def __next__(self) -> str:
            line = self.readline()
            if not line:
                raise StopIteration
            return line

    stream = TrackingStream()
    release = threading.Event()
    started = threading.Event()

    def opener(_url: str, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        started.set()
        assert release.wait(timeout=5)
        return FakeResponse(IMAGE_BYTES)

    outcome: list[ExportReport] = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            run_export_stream(stream, tmp_path, max_workers=4, opener=opener)  # type: ignore[arg-type]
        )
    )
    worker.start()
    assert started.wait(timeout=2)
    time.sleep(0.05)
    with stream.lock:
        assert stream.index == 1 + MAX_PENDING_DOWNLOADS
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert outcome[0].succeeded == 20


def test_disk_gate_runs_before_output_creation_or_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Moving the disk check after mkdir/network must cause observable side effects first."""
    Usage = namedtuple("Usage", "total used free")
    opened = False

    def opener(*_args: object, **_kwargs: object) -> FakeResponse:
        nonlocal opened
        opened = True
        return FakeResponse(IMAGE_BYTES)

    monkeypatch.setattr(shutil, "disk_usage", lambda _path: Usage(100, 99, 1))
    with pytest.raises(InsufficientDiskError, match="required"):
        run_export(
            stdin_text=manifest_jsonl(1),
            output_root=tmp_path / "new-output",
            formats={"files", "zip"},
            opener=opener,
        )
    assert not (tmp_path / "new-output").exists()
    assert opened is False


def test_outputs_match_manifest_and_contain_no_signed_urls(tmp_path: Path) -> None:
    """Serializing ManifestItem directly must leak download_url/Signature into artifacts."""
    result = run_export(
        stdin_text=manifest_jsonl(3),
        output_root=tmp_path,
        formats={"files", "zip", "csv", "xlsx"},
        opener=fake_oss_opener,
    )
    assert result.planned == result.succeeded == 3
    assert result.failed == 0
    with ZipFile(tmp_path / "photos.zip") as archive:
        assert archive.namelist() == [item.relative_path for item in result.items]
        assert all(archive.read(name) == IMAGE_BYTES for name in archive.namelist())
    csv_bytes = (tmp_path / "manifest.csv").read_bytes()
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    report_text = (tmp_path / "export-report.json").read_text(encoding="utf-8")
    for artifact_text in (report_text, csv_bytes.decode("utf-8-sig")):
        assert "download_url" not in artifact_text
        assert "https://" not in artifact_text
        assert "Signature=" not in artifact_text
    assert not list(tmp_path.rglob("*.part"))


def test_all_report_metadata_is_sanitized_against_url_and_signature_fragments(
    tmp_path: Path,
) -> None:
    """Sanitizing only errors must allow hostile metadata to persist signed secrets."""
    row = valid_row(
        category="https://host.invalid/photo?Signature=category-secret",
        storage_key="objects/photo.jpg?Signature=key-secret",
    )
    header = {
        "schema": SCHEMA,
        "kind": "manifest",
        "planned_count": 1,
        "planned_bytes": len(IMAGE_BYTES),
    }
    text = json.dumps(header) + "\n" + json.dumps(row) + "\n"
    run_export(
        text,
        tmp_path,
        formats={"files", "csv", "xlsx"},
        opener=fake_oss_opener,
    )
    report_text = (tmp_path / "export-report.json").read_text(encoding="utf-8")
    csv_text = (tmp_path / "manifest.csv").read_text(encoding="utf-8-sig")
    workbook = load_workbook(tmp_path / "manifest.xlsx")
    workbook_text = " ".join(
        str(cell.value or "")
        for sheet in workbook.worksheets
        for row_cells in sheet.iter_rows()
        for cell in row_cells
    )
    for artifact_text in (report_text, csv_text, workbook_text):
        assert "https://" not in artifact_text
        assert "Signature=" not in artifact_text
        assert "category-secret" not in artifact_text
        assert "key-secret" not in artifact_text


def test_xlsx_has_manifest_formatting_and_failure_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting planned failures from XLSX must hide partial-export evidence."""
    calls = 0

    def opener(_url: str, *, timeout: int) -> FakeResponse:
        nonlocal calls
        assert timeout == 30
        calls += 1
        if calls == 1:
            raise RuntimeError(
                "GET https://oss.invalid/p.jpg?OSSAccessKeyId=id&Signature=top-secret failed"
            )
        return FakeResponse(IMAGE_BYTES)

    monkeypatch.setattr(exporter, "RETRY_DELAYS", ())
    result = run_export(
        stdin_text=manifest_jsonl(2),
        output_root=tmp_path,
        formats={"files", "xlsx"},
        max_workers=1,
        opener=opener,
    )
    assert (result.succeeded, result.failed) == (1, 1)
    workbook = load_workbook(tmp_path / "manifest.xlsx")
    assert workbook.sheetnames == ["Manifest", "Failures"]
    manifest = workbook["Manifest"]
    failures = workbook["Failures"]
    assert manifest.freeze_panes == "A2"
    assert manifest.auto_filter.ref == manifest.dimensions
    assert manifest.max_row == 3
    headers = [cell.value for cell in manifest[1]]
    group_column = headers.index("group_id") + 1
    photo_column = headers.index("photo_id") + 1
    assert manifest.cell(2, group_column).number_format == "@"
    assert manifest.cell(2, photo_column).number_format == "@"
    assert failures.freeze_panes == "A2"
    assert failures.max_row == 2
    failure_text = " ".join(str(cell.value or "") for row in failures for cell in row)
    assert "https://" not in failure_text
    assert "Signature=" not in failure_text
    assert not (tmp_path / result.items[0].relative_path).exists()
    assert (tmp_path / result.items[1].relative_path).read_bytes() == IMAGE_BYTES


def test_run_export_defaults_to_files_and_writes_atomic_report(tmp_path: Path) -> None:
    """Treating formats=None as every format must create unrequested artifacts."""
    result = run_export(manifest_jsonl(1), tmp_path, opener=fake_oss_opener)
    assert result.succeeded == 1
    assert (tmp_path / "export-report.json").is_file()
    assert not (tmp_path / "photos.zip").exists()
    assert not (tmp_path / "manifest.csv").exists()
    assert not (tmp_path / "manifest.xlsx").exists()
