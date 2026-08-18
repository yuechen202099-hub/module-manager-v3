from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Protocol
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

from app.services.photo_storage import open_validated_remote_image_url


MAX_EXTERNAL_PHOTO_BYTES = 30 * 1024 * 1024
MAX_EXTERNAL_PHOTO_CHUNK_BYTES = 1024 * 1024
REMOTE_IMAGE_USER_AGENT = "module-manager-v3-external-photo-migrator/1.0"
SUPPORTED_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
    "BMP": ("image/bmp", ".bmp"),
}


class PhotoTransferError(RuntimeError):
    pass


class OssObjectConflictError(RuntimeError):
    pass


class OssVerificationError(RuntimeError):
    pass


class RemoteImageOpener(Protocol):
    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        allowed_hosts: Iterable[str],
        app_env: str,
    ) -> AbstractContextManager[Any]: ...


@dataclass(frozen=True, slots=True)
class ExternalPhotoSource:
    photo_id: str
    team_id: str
    group_id: str
    url: str
    filename: str


@dataclass(frozen=True, slots=True)
class DownloadPolicy:
    allowed_hosts: frozenset[str]
    timeout_seconds: float = 20
    max_bytes: int = MAX_EXTERNAL_PHOTO_BYTES
    chunk_bytes: int = MAX_EXTERNAL_PHOTO_CHUNK_BYTES


@dataclass(frozen=True, slots=True)
class DownloadedPhoto:
    path: Path
    sha256: str
    byte_size: int
    content_type: str
    suffix: str


@dataclass(frozen=True, slots=True)
class OssObjectReceipt:
    bucket: str
    key: str
    sha256: str
    byte_size: int
    content_type: str
    reused: bool


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is None and callable(getattr(response, "getcode", None)):
        status = response.getcode()
    return int(status) if status is not None else None


def _header_value(headers: Any, name: str) -> Any:
    if headers is None:
        return None
    direct = headers.get(name)
    if direct is not None:
        return direct
    target = name.lower()
    for header_name, value in headers.items():
        if str(header_name).lower() == target:
            return value
    return None


def _parse_content_length(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw.isascii() or not raw.isdecimal():
        raise PhotoTransferError("external photo has invalid Content-Length")
    return int(raw)


def _new_private_temp_file(temp_dir: Path) -> tuple[Path, BinaryIO]:
    directory = Path(temp_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor = -1
    target: Path | None = None
    try:
        descriptor, filename = tempfile.mkstemp(
            prefix=".external-photo-",
            suffix=".part",
            dir=directory,
        )
        target = Path(filename)
        os.chmod(target, 0o600)
        output = os.fdopen(descriptor, "wb")
        descriptor = -1
        return target, output
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if target is not None:
            target.unlink(missing_ok=True)
        raise


def _bounded_image_edges(path: Path, byte_size: int) -> tuple[bytes, bytes]:
    with path.open("rb") as image_file:
        header = image_file.read(16)
        if byte_size > 32:
            image_file.seek(-32, os.SEEK_END)
        else:
            image_file.seek(0)
        tail = image_file.read(32)
    return header, tail


def _verify_image_file(path: Path, byte_size: int) -> tuple[str, str]:
    if byte_size <= 0:
        raise PhotoTransferError("external photo is empty")
    try:
        if path.stat().st_size != byte_size:
            raise PhotoTransferError("external photo file size changed")
        with Image.open(path) as image:
            image_format = str(image.format or "").upper()
            image.verify()
    except PhotoTransferError:
        raise
    except Exception as exc:
        raise PhotoTransferError("external photo has invalid image bytes") from exc

    detected = SUPPORTED_IMAGE_FORMATS.get(image_format)
    if detected is None:
        raise PhotoTransferError("external photo has invalid image format")

    header, tail = _bounded_image_edges(path, byte_size)
    complete = True
    if image_format == "JPEG":
        complete = header.startswith(b"\xff\xd8") and tail.endswith(b"\xff\xd9")
    elif image_format == "PNG":
        complete = header.startswith(b"\x89PNG\r\n\x1a\n") and tail.endswith(
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    elif image_format == "WEBP":
        complete = (
            header.startswith(b"RIFF")
            and header[8:12] == b"WEBP"
            and len(header) >= 12
            and int.from_bytes(header[4:8], "little") + 8 == byte_size
        )
    elif image_format == "BMP":
        complete = (
            header.startswith(b"BM")
            and len(header) >= 6
            and int.from_bytes(header[2:6], "little") == byte_size
        )
    if not complete:
        raise PhotoTransferError("external photo has invalid image completeness")
    return detected


def download_external_photo(
    source: ExternalPhotoSource,
    policy: DownloadPolicy,
    *,
    temp_dir: Path,
    opener: RemoteImageOpener = open_validated_remote_image_url,
) -> DownloadedPhoto:
    if policy.max_bytes != MAX_EXTERNAL_PHOTO_BYTES:
        raise ValueError("external photo max_bytes must be exactly 30 MiB")
    if policy.chunk_bytes <= 0 or policy.chunk_bytes > MAX_EXTERNAL_PHOTO_CHUNK_BYTES:
        raise ValueError("external photo chunk_bytes must be between 1 byte and 1 MiB")

    target: Path | None = None
    try:
        with opener(
            source.url,
            headers={"User-Agent": REMOTE_IMAGE_USER_AGENT, "Accept": "image/*"},
            timeout=policy.timeout_seconds,
            allowed_hosts=policy.allowed_hosts,
            app_env="production",
        ) as response:
            status = _response_status(response)
            if status is not None and 300 <= status < 400:
                raise PhotoTransferError("external photo redirect is not allowed")
            if status == 206:
                raise PhotoTransferError("external photo partial response is not allowed")
            if status is not None and status != 200:
                raise PhotoTransferError("external photo returned an unexpected HTTP status")

            declared = _parse_content_length(_header_value(getattr(response, "headers", None), "Content-Length"))
            if declared is not None and declared > policy.max_bytes:
                raise PhotoTransferError("external photo is too large")

            target, output = _new_private_temp_file(temp_dir)
            digest = hashlib.sha256()
            byte_size = 0
            with output:
                while True:
                    chunk = response.read(policy.chunk_bytes)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise PhotoTransferError("external photo returned invalid body bytes")
                    if len(chunk) > policy.chunk_bytes:
                        raise PhotoTransferError("external photo returned an oversized stream chunk")
                    byte_size += len(chunk)
                    if byte_size > policy.max_bytes:
                        raise PhotoTransferError("external photo is too large")
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())

        if byte_size == 0:
            raise PhotoTransferError("external photo is empty")
        if declared is not None and byte_size != declared:
            raise PhotoTransferError("external photo is partial or has a length mismatch")
        content_type, suffix = _verify_image_file(target, byte_size)
        return DownloadedPhoto(
            path=target,
            sha256=digest.hexdigest(),
            byte_size=byte_size,
            content_type=content_type,
            suffix=suffix,
        )
    except BaseException:
        if target is not None:
            target.unlink(missing_ok=True)
        raise


def _is_no_such_key(exc: Exception) -> bool:
    return getattr(exc, "status", None) == 404 and getattr(exc, "code", None) == "NoSuchKey"


def _head_object_or_none(bucket: Any, key: str) -> Any | None:
    try:
        return bucket.head_object(key)
    except Exception as exc:
        if _is_no_such_key(exc):
            return None
        raise


def _head_metadata(result: Any) -> tuple[int | None, str | None, str | None]:
    headers = getattr(result, "headers", None)
    raw_length = _header_value(headers, "Content-Length")
    if raw_length is None:
        raw_length = getattr(result, "content_length", None)
    try:
        content_length = int(raw_length) if raw_length is not None else None
    except (TypeError, ValueError):
        content_length = None
    content_type = _header_value(headers, "Content-Type")
    if content_type is None:
        content_type = getattr(result, "content_type", None)
    content_sha256 = _header_value(headers, "x-oss-meta-sha256")
    return content_length, content_sha256, content_type


def _verify_object_metadata(
    result: Any,
    photo: DownloadedPhoto,
    *,
    error_type: type[RuntimeError],
) -> None:
    content_length, content_sha256, content_type = _head_metadata(result)
    if (
        content_length != photo.byte_size
        or content_sha256 != photo.sha256
        or content_type != photo.content_type
    ):
        raise error_type("OSS object metadata does not exactly match downloaded photo")


def _is_forbid_overwrite_conflict(exc: Exception) -> bool:
    return getattr(exc, "status", None) == 409 and getattr(exc, "code", None) == "FileAlreadyExists"


def _receipt(
    bucket_name: str,
    key: str,
    photo: DownloadedPhoto,
    *,
    reused: bool,
) -> OssObjectReceipt:
    return OssObjectReceipt(
        bucket=bucket_name,
        key=key,
        sha256=photo.sha256,
        byte_size=photo.byte_size,
        content_type=photo.content_type,
        reused=reused,
    )


def store_downloaded_photo(
    bucket: Any,
    bucket_name: str,
    key: str,
    photo: DownloadedPhoto,
) -> OssObjectReceipt:
    before = _head_object_or_none(bucket, key)
    if before is not None:
        _verify_object_metadata(before, photo, error_type=OssObjectConflictError)
        return _receipt(bucket_name, key, photo, reused=True)

    headers = {
        "Content-Type": photo.content_type,
        "x-oss-meta-sha256": photo.sha256,
        "x-oss-forbid-overwrite": "true",
    }
    try:
        bucket.put_object_from_file(key, str(photo.path), headers=headers)
    except Exception as exc:
        if not _is_forbid_overwrite_conflict(exc):
            raise
        raced = _head_object_or_none(bucket, key)
        if raced is None:
            raise OssVerificationError("concurrent OSS object is missing") from exc
        _verify_object_metadata(raced, photo, error_type=OssObjectConflictError)
        return _receipt(bucket_name, key, photo, reused=True)

    after = _head_object_or_none(bucket, key)
    if after is None:
        raise OssVerificationError("uploaded OSS object is missing")
    _verify_object_metadata(after, photo, error_type=OssVerificationError)
    return _receipt(bucket_name, key, photo, reused=False)


def cleanup_download(photo: DownloadedPhoto) -> None:
    photo.path.unlink(missing_ok=True)


def redact_source_url(url: str) -> str:
    raw = str(url or "")
    try:
        parsed = urlsplit(raw)
        netloc = parsed.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except ValueError:
        without_secrets = raw.split("#", 1)[0].split("?", 1)[0]
        if "://" in without_secrets:
            scheme, remainder = without_secrets.split("://", 1)
            return f"{scheme}://{remainder.rsplit('@', 1)[-1]}"
        return without_secrets.rsplit("@", 1)[-1]


__all__ = [
    "DownloadPolicy",
    "DownloadedPhoto",
    "ExternalPhotoSource",
    "OssObjectConflictError",
    "OssObjectReceipt",
    "OssVerificationError",
    "PhotoTransferError",
    "RemoteImageOpener",
    "cleanup_download",
    "download_external_photo",
    "redact_source_url",
    "store_downloaded_photo",
]
