from __future__ import annotations

import hashlib
import os
import secrets
import stat
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator, Protocol
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

from app.services.photo_storage import open_validated_remote_image_url


MAX_EXTERNAL_PHOTO_BYTES = 30 * 1024 * 1024
MAX_EXTERNAL_PHOTO_CHUNK_BYTES = 1024 * 1024
REMOTE_IMAGE_USER_AGENT = "module-manager-v3-external-photo-migrator/1.0"
SUPPORTED_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
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


@dataclass(slots=True)
class _PrivateDirectoryBoundary:
    path: Path
    device: int
    inode: int
    descriptor: int | None


@dataclass(slots=True)
class _StablePhotoFile:
    boundary: _PrivateDirectoryBoundary
    file: BinaryIO
    path: Path
    device: int
    inode: int
    upload_path: Path


def _response_status(response: Any) -> int:
    try:
        status = getattr(response, "status", None)
        if status is None:
            getcode = getattr(response, "getcode", None)
            if not callable(getcode):
                raise ValueError("missing status")
            status = getcode()
    except Exception as exc:
        raise PhotoTransferError("external photo has invalid HTTP status") from exc
    if isinstance(status, bool):
        raise PhotoTransferError("external photo has invalid HTTP status")
    if isinstance(status, int):
        return status
    if isinstance(status, str):
        raw = status.strip()
        if raw.isascii() and raw.isdecimal():
            return int(raw)
    raise PhotoTransferError("external photo has invalid HTTP status")


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


def _identity(file_stat: os.stat_result) -> tuple[int, int]:
    return file_stat.st_dev, file_stat.st_ino


def _is_linklike(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _validate_private_directory(path: Path, path_stat: os.stat_result) -> None:
    if _is_linklike(path, path_stat) or not stat.S_ISDIR(path_stat.st_mode):
        raise PhotoTransferError("external photo private temp directory is unsafe")
    if os.name != "nt":
        if path_stat.st_uid != os.geteuid():
            raise PhotoTransferError("external photo private temp directory has the wrong owner")
        if stat.S_IMODE(path_stat.st_mode) != 0o700:
            raise PhotoTransferError("external photo private temp directory permissions are unsafe")


def _open_private_directory(temp_dir: Path, *, create: bool) -> _PrivateDirectoryBoundary:
    directory = Path(temp_dir)
    try:
        initial = os.lstat(directory)
    except FileNotFoundError:
        if not create:
            raise PhotoTransferError("external photo private temp directory is missing") from None
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        except FileExistsError:
            pass
        except OSError as exc:
            raise PhotoTransferError("external photo private temp directory cannot be created") from exc
        try:
            initial = os.lstat(directory)
        except OSError as exc:
            raise PhotoTransferError("external photo private temp directory is unavailable") from exc
    except OSError as exc:
        raise PhotoTransferError("external photo private temp directory is unavailable") from exc

    _validate_private_directory(directory, initial)
    descriptor: int | None = None
    if os.name != "nt" and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(directory, flags)
            opened = os.fstat(descriptor)
            _validate_private_directory(directory, opened)
            if _identity(opened) != _identity(initial):
                raise PhotoTransferError("external photo private temp directory changed")
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            raise
    else:
        try:
            opened = os.lstat(directory)
        except OSError as exc:
            raise PhotoTransferError("external photo private temp directory is unavailable") from exc
        _validate_private_directory(directory, opened)
        if _identity(opened) != _identity(initial):
            raise PhotoTransferError("external photo private temp directory changed")
    return _PrivateDirectoryBoundary(directory, initial.st_dev, initial.st_ino, descriptor)


def _verify_private_directory(boundary: _PrivateDirectoryBoundary) -> None:
    try:
        current = os.lstat(boundary.path)
    except OSError as exc:
        raise PhotoTransferError("external photo private temp directory changed") from exc
    _validate_private_directory(boundary.path, current)
    if _identity(current) != (boundary.device, boundary.inode):
        raise PhotoTransferError("external photo private temp directory changed")
    if boundary.descriptor is not None:
        opened = os.fstat(boundary.descriptor)
        _validate_private_directory(boundary.path, opened)
        if _identity(opened) != (boundary.device, boundary.inode):
            raise PhotoTransferError("external photo private temp directory changed")


def _close_private_directory(boundary: _PrivateDirectoryBoundary | None) -> None:
    if boundary is not None and boundary.descriptor is not None:
        os.close(boundary.descriptor)
        boundary.descriptor = None


def _validate_private_file(file_stat: os.stat_result) -> None:
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise PhotoTransferError("external photo private temp file is unsafe")
    if os.name != "nt":
        if file_stat.st_uid != os.geteuid() or stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise PhotoTransferError("external photo private temp file permissions are unsafe")


def _unlink_private_target(target: Path, boundary: _PrivateDirectoryBoundary) -> None:
    try:
        if boundary.descriptor is not None:
            os.unlink(target.name, dir_fd=boundary.descriptor)
            return
        _verify_private_directory(boundary)
        target.unlink(missing_ok=True)
    except (FileNotFoundError, PhotoTransferError, OSError):
        return


def _new_private_temp_file(
    boundary: _PrivateDirectoryBoundary,
) -> tuple[Path, BinaryIO, tuple[int, int]]:
    descriptor = -1
    target: Path | None = None
    try:
        _verify_private_directory(boundary)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        for _attempt in range(64):
            name = f".external-photo-{secrets.token_hex(16)}.part"
            target = boundary.path / name
            try:
                if boundary.descriptor is not None:
                    descriptor = os.open(name, flags, 0o600, dir_fd=boundary.descriptor)
                else:
                    descriptor = os.open(target, flags, 0o600)
                break
            except FileExistsError:
                continue
        else:
            raise PhotoTransferError("external photo private temp filename collision")

        opened = os.fstat(descriptor)
        _validate_private_file(opened)
        _verify_private_directory(boundary)
        current = os.lstat(target)
        _validate_private_file(current)
        if _identity(current) != _identity(opened):
            raise PhotoTransferError("external photo private temp file changed")
        output = os.fdopen(descriptor, "wb")
        descriptor = -1
        return target, output, _identity(opened)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if target is not None:
            _unlink_private_target(target, boundary)
        raise


def _open_verified_private_file(
    path: Path,
    boundary: _PrivateDirectoryBoundary,
    *,
    expected_identity: tuple[int, int] | None,
) -> tuple[BinaryIO, tuple[int, int]]:
    _verify_private_directory(boundary)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = -1
    try:
        if boundary.descriptor is not None:
            descriptor = os.open(path.name, flags, dir_fd=boundary.descriptor)
        else:
            descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        _validate_private_file(opened)
        if expected_identity is not None and _identity(opened) != expected_identity:
            raise PhotoTransferError("external photo private temp file changed")
        _verify_private_directory(boundary)
        current = os.lstat(path)
        _validate_private_file(current)
        if _identity(current) != _identity(opened):
            raise PhotoTransferError("external photo private temp file changed")
        image_file = os.fdopen(descriptor, "rb")
        descriptor = -1
        return image_file, _identity(opened)
    except BaseException as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if isinstance(exc, PhotoTransferError):
            raise
        raise PhotoTransferError("external photo private temp file changed") from exc


def _bounded_image_edges(image_file: BinaryIO, byte_size: int) -> tuple[bytes, bytes]:
    image_file.seek(0)
    header = image_file.read(16)
    if byte_size > 32:
        image_file.seek(-32, os.SEEK_END)
    else:
        image_file.seek(0)
    tail = image_file.read(32)
    return header, tail


def _verify_image_file(
    path: Path,
    byte_size: int,
    *,
    boundary: _PrivateDirectoryBoundary,
    expected_identity: tuple[int, int],
) -> tuple[str, str]:
    if byte_size <= 0:
        raise PhotoTransferError("external photo is empty")
    try:
        image_file, _opened_identity = _open_verified_private_file(
            path,
            boundary,
            expected_identity=expected_identity,
        )
        with image_file:
            if os.fstat(image_file.fileno()).st_size != byte_size:
                raise PhotoTransferError("external photo file size changed")
            with Image.open(image_file) as image:
                image_format = str(image.format or "").upper()
                image.verify()
            header, tail = _bounded_image_edges(image_file, byte_size)
    except PhotoTransferError:
        raise
    except Exception as exc:
        raise PhotoTransferError("external photo has invalid image bytes") from exc

    detected = SUPPORTED_IMAGE_FORMATS.get(image_format)
    if detected is None:
        raise PhotoTransferError("external photo has invalid image format")

    complete = True
    if image_format == "JPEG":
        complete = header.startswith(b"\xff\xd8") and tail.endswith(b"\xff\xd9")
    elif image_format == "PNG":
        complete = header.startswith(b"\x89PNG\r\n\x1a\n") and tail.endswith(
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
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

    boundary: _PrivateDirectoryBoundary | None = None
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
            if 300 <= status < 400:
                raise PhotoTransferError("external photo redirect is not allowed")
            if status == 206:
                raise PhotoTransferError("external photo partial response is not allowed")
            if status != 200:
                raise PhotoTransferError("external photo returned an unexpected HTTP status")

            declared = _parse_content_length(_header_value(getattr(response, "headers", None), "Content-Length"))
            if declared is not None and declared > policy.max_bytes:
                raise PhotoTransferError("external photo is too large")

            boundary = _open_private_directory(temp_dir, create=True)
            target, output, file_identity = _new_private_temp_file(boundary)
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
        content_type, suffix = _verify_image_file(
            target,
            byte_size,
            boundary=boundary,
            expected_identity=file_identity,
        )
        return DownloadedPhoto(
            path=target,
            sha256=digest.hexdigest(),
            byte_size=byte_size,
            content_type=content_type,
            suffix=suffix,
        )
    except BaseException:
        if target is not None and boundary is not None:
            _unlink_private_target(target, boundary)
        raise
    finally:
        _close_private_directory(boundary)


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


def _stable_descriptor_path(file: BinaryIO, identity: tuple[int, int], fallback: Path) -> Path:
    if os.name != "nt":
        for directory in (Path("/proc/self/fd"), Path("/dev/fd")):
            candidate = directory / str(file.fileno())
            try:
                if _identity(os.stat(candidate)) == identity:
                    return candidate
            except OSError:
                continue
    return fallback


def _verify_stable_photo_path(stable: _StablePhotoFile) -> None:
    _verify_private_directory(stable.boundary)
    try:
        current = os.lstat(stable.path)
    except OSError as exc:
        raise PhotoTransferError("downloaded photo file changed") from exc
    _validate_private_file(current)
    if _identity(current) != (stable.device, stable.inode):
        raise PhotoTransferError("downloaded photo file changed")


@contextmanager
def _validated_photo_for_upload(photo: DownloadedPhoto) -> Iterator[_StablePhotoFile]:
    boundary: _PrivateDirectoryBoundary | None = None
    photo_file: BinaryIO | None = None
    try:
        boundary = _open_private_directory(photo.path.parent, create=False)
        photo_file, file_identity = _open_verified_private_file(
            photo.path,
            boundary,
            expected_identity=None,
        )
        digest = hashlib.sha256()
        byte_size = 0
        while chunk := photo_file.read(MAX_EXTERNAL_PHOTO_CHUNK_BYTES):
            digest.update(chunk)
            byte_size += len(chunk)
            if byte_size > MAX_EXTERNAL_PHOTO_BYTES:
                raise PhotoTransferError("downloaded photo file changed")
        if byte_size != photo.byte_size or digest.hexdigest() != photo.sha256:
            raise PhotoTransferError("downloaded photo file changed")
        photo_file.seek(0)
        upload_path = _stable_descriptor_path(photo_file, file_identity, photo.path)
        stable = _StablePhotoFile(
            boundary=boundary,
            file=photo_file,
            path=photo.path,
            device=file_identity[0],
            inode=file_identity[1],
            upload_path=upload_path,
        )
        _verify_stable_photo_path(stable)
        yield stable
    finally:
        if photo_file is not None:
            photo_file.close()
        _close_private_directory(boundary)


def _private_entry_stat(path: Path, boundary: _PrivateDirectoryBoundary) -> os.stat_result:
    if boundary.descriptor is not None:
        return os.stat(path.name, dir_fd=boundary.descriptor, follow_symlinks=False)
    _verify_private_directory(boundary)
    result = os.lstat(path)
    _verify_private_directory(boundary)
    return result


def _rename_private_entry(
    source: Path,
    destination: Path,
    boundary: _PrivateDirectoryBoundary,
) -> None:
    if boundary.descriptor is not None:
        os.rename(
            source.name,
            destination.name,
            src_dir_fd=boundary.descriptor,
            dst_dir_fd=boundary.descriptor,
        )
        return
    _verify_private_directory(boundary)
    os.rename(source, destination)
    _verify_private_directory(boundary)


def _new_cleanup_quarantine(boundary: _PrivateDirectoryBoundary) -> Path:
    for _attempt in range(64):
        candidate = boundary.path / f".external-photo-cleanup-{secrets.token_hex(16)}.part"
        try:
            _private_entry_stat(candidate, boundary)
        except FileNotFoundError:
            return candidate
    raise PhotoTransferError("external photo cleanup filename collision")


def _restore_quarantined_replacement(
    stable: _StablePhotoFile,
    quarantine: Path,
) -> None:
    try:
        _private_entry_stat(stable.path, stable.boundary)
    except FileNotFoundError:
        _rename_private_entry(quarantine, stable.path, stable.boundary)


def _cleanup_stable_photo(stable: _StablePhotoFile) -> None:
    if stable.boundary.descriptor is None:
        stable.file.close()
    _verify_stable_photo_path(stable)

    quarantine = _new_cleanup_quarantine(stable.boundary)
    _rename_private_entry(stable.path, quarantine, stable.boundary)
    quarantined = _private_entry_stat(quarantine, stable.boundary)
    if _identity(quarantined) != (stable.device, stable.inode):
        _restore_quarantined_replacement(stable, quarantine)
        return
    _validate_private_file(quarantined)

    quarantined = _private_entry_stat(quarantine, stable.boundary)
    if _identity(quarantined) != (stable.device, stable.inode):
        _restore_quarantined_replacement(stable, quarantine)
        return
    _validate_private_file(quarantined)
    if stable.boundary.descriptor is not None:
        os.unlink(quarantine.name, dir_fd=stable.boundary.descriptor)
        return
    _verify_private_directory(stable.boundary)
    quarantine.unlink()
    _verify_private_directory(stable.boundary)


def store_downloaded_photo(
    bucket: Any,
    bucket_name: str,
    key: str,
    photo: DownloadedPhoto,
) -> OssObjectReceipt:
    with _validated_photo_for_upload(photo) as stable:
        before = _head_object_or_none(bucket, key)
        _verify_stable_photo_path(stable)
        if before is not None:
            _verify_object_metadata(before, photo, error_type=OssObjectConflictError)
            return _receipt(bucket_name, key, photo, reused=True)

        headers = {
            "Content-Type": photo.content_type,
            "x-oss-meta-sha256": photo.sha256,
            "x-oss-forbid-overwrite": "true",
        }
        _verify_stable_photo_path(stable)
        try:
            bucket.put_object_from_file(key, str(stable.upload_path), headers=headers)
        except Exception as exc:
            if not _is_forbid_overwrite_conflict(exc):
                raise
            raced = _head_object_or_none(bucket, key)
            _verify_stable_photo_path(stable)
            if raced is None:
                raise OssVerificationError("concurrent OSS object is missing") from exc
            _verify_object_metadata(raced, photo, error_type=OssObjectConflictError)
            return _receipt(bucket_name, key, photo, reused=True)

        after = _head_object_or_none(bucket, key)
        _verify_stable_photo_path(stable)
        if after is None:
            raise OssVerificationError("uploaded OSS object is missing")
        _verify_object_metadata(after, photo, error_type=OssVerificationError)
        return _receipt(bucket_name, key, photo, reused=False)


def cleanup_download(photo: DownloadedPhoto) -> None:
    try:
        with _validated_photo_for_upload(photo) as stable:
            _cleanup_stable_photo(stable)
    except (FileNotFoundError, PhotoTransferError, OSError):
        return


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
