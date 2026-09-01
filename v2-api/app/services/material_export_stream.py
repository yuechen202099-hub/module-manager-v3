from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import time
from typing import Any

from app.core.config import get_settings
from app.services.photo_storage import oss_server_endpoint, require_oss_client


class MaterialExportOssUnavailable(RuntimeError):
    pass


class MaterialExportObjectMismatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MaterialExportFileSnapshot:
    file_id: str
    storage_bucket: str
    storage_key: str
    byte_size: int
    sha256: str
    content_type: str

    @classmethod
    def from_row(cls, row: object) -> "MaterialExportFileSnapshot":
        storage_key = str(getattr(row, "storage_key", "") or "").strip()
        sha256 = str(getattr(row, "sha256", "") or "").strip().lower()
        byte_size = getattr(row, "byte_size", None)
        if not storage_key or byte_size is None or int(byte_size) < 0 or len(sha256) != 64:
            raise MaterialExportObjectMismatch("导出文件的 OSS 存储快照不完整")
        return cls(
            file_id=str(getattr(row, "id", "")),
            storage_bucket=str(getattr(row, "storage_bucket", "") or "").strip(),
            storage_key=storage_key,
            byte_size=int(byte_size),
            sha256=sha256,
            content_type=str(
                getattr(row, "content_type", "application/octet-stream")
                or "application/octet-stream"
            ),
        )


@dataclass(slots=True)
class StreamPolicy:
    bytes_per_second: int = 250_000
    chunk_bytes: int = 65_536

    def __post_init__(self) -> None:
        if self.bytes_per_second <= 0 or self.chunk_bytes <= 0:
            raise ValueError("流式导出限速参数必须大于零")


def _header_value(head: object, name: str) -> str:
    headers = getattr(head, "headers", {}) or {}
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value or "").strip()
    return ""


def head_export_object(*, bucket: Any, snapshot: MaterialExportFileSnapshot) -> None:
    head = bucket.head_object(snapshot.storage_key)
    actual_size = getattr(head, "content_length", None)
    if actual_size is None:
        actual_size = _header_value(head, "content-length")
    if int(actual_size or -1) != snapshot.byte_size:
        raise MaterialExportObjectMismatch("OSS 对象大小与清单不一致")
    metadata_sha = _header_value(head, "x-oss-meta-sha256").lower()
    if metadata_sha and metadata_sha != snapshot.sha256:
        raise MaterialExportObjectMismatch("OSS 对象 SHA256 与清单不一致")


def iter_export_object(
    *,
    bucket: Any,
    key: str,
    expected_size: int,
    policy: StreamPolicy,
    on_complete: Callable[[int], None],
    on_abort: Callable[[int], None],
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Iterator[bytes]:
    result = bucket.get_object(key)
    sent = 0
    started = monotonic()
    try:
        while True:
            chunk = result.read(policy.chunk_bytes)
            if not chunk:
                break
            if len(chunk) > policy.chunk_bytes:
                raise MaterialExportObjectMismatch("OSS 返回分块超过安全上限")
            sent += len(chunk)
            target_elapsed = sent / policy.bytes_per_second
            delay = target_elapsed - (monotonic() - started)
            if delay > 0:
                sleeper(delay)
            yield chunk
        if sent != expected_size:
            raise MaterialExportObjectMismatch("OSS 对象大小与清单不一致")
        on_complete(sent)
    except GeneratorExit:
        on_abort(sent)
        raise
    except BaseException:
        on_abort(sent)
        raise


def build_export_stream(
    file_row: object,
    *,
    on_complete: Callable[[int], None],
    on_abort: Callable[[int], None],
    bucket_factory: Callable[[str, str], Any] | None = None,
    policy: StreamPolicy | None = None,
) -> Iterator[bytes]:
    settings = get_settings()
    endpoint = oss_server_endpoint(require_internal=True)
    if not endpoint:
        raise MaterialExportOssUnavailable("未配置 OSS 内网端点，禁止回退公网下载")
    snapshot = MaterialExportFileSnapshot.from_row(file_row)
    configured_bucket = str(settings.oss_bucket or "").strip()
    if snapshot.storage_bucket and configured_bucket and snapshot.storage_bucket != configured_bucket:
        raise MaterialExportOssUnavailable("文件存储桶与服务器配置不一致")
    if bucket_factory is None:
        bucket = require_oss_client(endpoint)
    else:
        bucket = bucket_factory(endpoint, snapshot.storage_bucket or configured_bucket)
    head_export_object(bucket=bucket, snapshot=snapshot)
    resolved_policy = policy or StreamPolicy(
        bytes_per_second=settings.material_export_bytes_per_second,
        chunk_bytes=settings.material_export_chunk_bytes,
    )
    return iter_export_object(
        bucket=bucket,
        key=snapshot.storage_key,
        expected_size=snapshot.byte_size,
        policy=resolved_policy,
        on_complete=on_complete,
        on_abort=on_abort,
    )
