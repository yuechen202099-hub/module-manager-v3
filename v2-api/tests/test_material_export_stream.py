from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from app.services.material_export_stream import (
    MaterialExportFileSnapshot,
    MaterialExportObjectMismatch,
    MaterialExportOssUnavailable,
    StreamPolicy,
    build_export_stream,
    iter_export_object,
)
from app.services import photo_storage


class FakeBucket:
    def __init__(self, payload: bytes, *, sha256: str = "a" * 64) -> None:
        self.payload = payload
        self.sha256 = sha256

    def head_object(self, _key: str):
        return SimpleNamespace(
            content_length=len(self.payload),
            headers={"x-oss-meta-sha256": self.sha256},
        )

    def get_object(self, _key: str):
        return BytesIO(self.payload)


def test_stream_policy_is_fixed_to_two_mbps_and_bounded_chunks() -> None:
    policy = StreamPolicy()
    assert policy.bytes_per_second == 250_000
    assert policy.chunk_bytes == 65_536


def test_iterator_throttles_without_disk_and_completes() -> None:
    payload = b"x" * 500_000
    bucket = FakeBucket(payload)
    clock = [0.0]
    completed: list[int] = []
    aborted: list[int] = []

    def monotonic() -> float:
        return clock[0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    chunks = list(
        iter_export_object(
            bucket=bucket,
            key="safe-key",
            expected_size=len(payload),
            policy=StreamPolicy(),
            on_complete=completed.append,
            on_abort=aborted.append,
            monotonic=monotonic,
            sleeper=sleep,
        )
    )
    assert b"".join(chunks) == payload
    assert max(map(len, chunks)) <= 65_536
    assert clock[0] >= 2.0
    assert completed == [len(payload)]
    assert aborted == []


def test_iterator_aborts_on_generator_close() -> None:
    aborted: list[int] = []
    stream = iter_export_object(
        bucket=FakeBucket(b"x" * 100_000),
        key="safe-key",
        expected_size=100_000,
        policy=StreamPolicy(bytes_per_second=10**9),
        on_complete=lambda _sent: pytest.fail("closed stream completed"),
        on_abort=aborted.append,
        sleeper=lambda _seconds: None,
    )
    first = next(stream)
    stream.close()
    assert aborted == [len(first)]


def test_iterator_rejects_wrong_object_size() -> None:
    with pytest.raises(MaterialExportObjectMismatch, match="大小"):
        list(
            iter_export_object(
                bucket=FakeBucket(b"short"),
                key="safe-key",
                expected_size=99,
                policy=StreamPolicy(bytes_per_second=10**9),
                on_complete=lambda _sent: None,
                on_abort=lambda _sent: None,
                sleeper=lambda _seconds: None,
            )
        )


def test_file_snapshot_accepts_only_server_persisted_fields() -> None:
    snapshot = MaterialExportFileSnapshot.from_row(
        SimpleNamespace(
            id="f-1",
            storage_bucket="bucket",
            storage_key="key",
            byte_size=12,
            sha256="a" * 64,
            content_type="image/jpeg",
        )
    )
    assert snapshot.file_id == "f-1"
    assert snapshot.storage_key == "key"


def test_build_stream_uses_internal_endpoint_only(monkeypatch) -> None:
    payload = b"photo-bytes"
    monkeypatch.setattr(photo_storage.settings, "oss_internal_endpoint", "oss-cn-internal.aliyuncs.com")
    monkeypatch.setattr(photo_storage.settings, "oss_endpoint", "oss-cn-public.aliyuncs.com")
    monkeypatch.setattr(photo_storage.settings, "oss_bucket", "bucket")
    endpoints: list[str] = []

    def bucket_factory(endpoint: str, bucket: str):
        endpoints.append(endpoint)
        assert bucket == "bucket"
        return FakeBucket(payload)

    file_row = SimpleNamespace(
        id="f-1",
        storage_bucket="bucket",
        storage_key="key",
        byte_size=len(payload),
        sha256="a" * 64,
        content_type="image/jpeg",
    )
    stream = build_export_stream(
        file_row,
        on_complete=lambda _sent: None,
        on_abort=lambda _sent: None,
        bucket_factory=bucket_factory,
        policy=StreamPolicy(bytes_per_second=10**9),
    )
    assert b"".join(stream) == payload
    assert endpoints == ["https://oss-cn-internal.aliyuncs.com"]


def test_missing_internal_endpoint_never_falls_back_publicly(monkeypatch) -> None:
    monkeypatch.setattr(photo_storage.settings, "oss_internal_endpoint", "")
    monkeypatch.setattr(photo_storage.settings, "oss_endpoint", "oss-cn-public.aliyuncs.com")
    with pytest.raises(MaterialExportOssUnavailable, match="OSS 内网端点"):
        build_export_stream(
            SimpleNamespace(
                id="f-1",
                storage_bucket="bucket",
                storage_key="key",
                byte_size=1,
                sha256="a" * 64,
                content_type="image/jpeg",
            ),
            on_complete=lambda _sent: None,
            on_abort=lambda _sent: None,
            bucket_factory=lambda _endpoint, _bucket: FakeBucket(b"x"),
        )
