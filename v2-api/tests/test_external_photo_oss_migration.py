from __future__ import annotations

import hashlib
import io
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.services import external_photo_oss_migration as migration
from app.services.external_photo_oss_migration import (
    DownloadPolicy,
    DownloadedPhoto,
    ExternalPhotoSource,
    OssObjectConflictError,
    OssVerificationError,
    PhotoTransferError,
    cleanup_download,
    download_external_photo,
    redact_source_url,
    store_downloaded_photo,
)


MAX_BYTES = 30 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
SOURCE = ExternalPhotoSource(
    "photo-secret-id",
    "team",
    "group",
    "https://img.example/a.jpg?token=secret#private",
    "a.jpg",
)
POLICY = DownloadPolicy(frozenset({"img.example"}))


def make_image_bytes(image_format: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), color=(21, 88, 144)).save(buffer, format=image_format)
    return buffer.getvalue()


JPEG_BYTES = make_image_bytes("JPEG")
PNG_BYTES = make_image_bytes("PNG")


def corrupt_png_idat_checksum(content: bytes) -> bytes:
    corrupted = bytearray(content)
    chunk_type_offset = content.index(b"IDAT")
    chunk_length = int.from_bytes(content[chunk_type_offset - 4 : chunk_type_offset], "big")
    checksum_offset = chunk_type_offset + 4 + chunk_length
    corrupted[checksum_offset] ^= 0x01
    return bytes(corrupted)


class FakeImageResponse:
    def __init__(
        self,
        content: bytes,
        *,
        headers: dict[str, str] | None = None,
        status: int = 200,
        fail_after_reads: int | None = None,
    ) -> None:
        self.content = content
        self.headers = headers or {}
        self.status = status
        self.fail_after_reads = fail_after_reads
        self.offset = 0
        self.read_sizes: list[int] = []
        self.read_calls = 0

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, size: int) -> bytes:
        self.read_calls += 1
        self.read_sizes.append(size)
        if self.fail_after_reads is not None and self.read_calls > self.fail_after_reads:
            raise KeyboardInterrupt("cancel transfer")
        chunk = self.content[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class GeneratedImageResponse(FakeImageResponse):
    def __init__(self, byte_count: int) -> None:
        super().__init__(b"")
        self.remaining = byte_count

    def read(self, size: int) -> bytes:
        self.read_calls += 1
        self.read_sizes.append(size)
        count = min(size, self.remaining)
        self.remaining -= count
        return b"x" * count


def test_download_uses_allowlist_pinned_no_redirect_opener_and_hashes_file(tmp_path: Path) -> None:
    opened: list[tuple[str, dict[str, Any]]] = []

    photo = download_external_photo(
        SOURCE,
        POLICY,
        temp_dir=tmp_path,
        opener=lambda url, **kwargs: opened.append((url, kwargs)) or FakeImageResponse(JPEG_BYTES),
    )

    assert opened == [
        (
            SOURCE.url,
            {
                "headers": {
                    "User-Agent": "module-manager-v3-external-photo-migrator/1.0",
                    "Accept": "image/*",
                },
                "timeout": 20,
                "allowed_hosts": frozenset({"img.example"}),
                "app_env": "production",
            },
        )
    ]
    assert photo.path.parent == tmp_path
    assert photo.path.read_bytes() == JPEG_BYTES
    assert photo.sha256 == hashlib.sha256(JPEG_BYTES).hexdigest()
    assert photo.byte_size == len(JPEG_BYTES)
    assert photo.content_type == "image/jpeg"
    assert photo.suffix == ".jpg"


def test_download_reads_only_bounded_chunks(tmp_path: Path) -> None:
    response = FakeImageResponse(JPEG_BYTES)

    photo = download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert photo.byte_size == len(JPEG_BYTES)
    assert response.read_sizes
    assert max(response.read_sizes) <= CHUNK_BYTES


def test_download_flushes_file_to_disk_with_fsync(tmp_path: Path, monkeypatch) -> None:
    fsync_calls: list[int] = []
    real_fsync = migration.os.fsync

    def tracking_fsync(file_descriptor: int) -> None:
        fsync_calls.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(migration.os, "fsync", tracking_fsync)

    download_external_photo(
        SOURCE,
        POLICY,
        temp_dir=tmp_path,
        opener=lambda *_a, **_k: FakeImageResponse(JPEG_BYTES),
    )

    assert len(fsync_calls) == 1


@pytest.mark.parametrize("max_bytes", [MAX_BYTES - 1, MAX_BYTES + 1])
def test_download_rejects_any_configured_limit_other_than_exactly_30_mib(tmp_path: Path, max_bytes: int) -> None:
    opened = False

    def opener(*_args, **_kwargs):  # noqa: ANN202
        nonlocal opened
        opened = True
        return FakeImageResponse(JPEG_BYTES)

    with pytest.raises(ValueError, match="exactly 30 MiB"):
        download_external_photo(
            SOURCE,
            DownloadPolicy(POLICY.allowed_hosts, max_bytes=max_bytes),
            temp_dir=tmp_path,
            opener=opener,
        )

    assert opened is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("chunk_bytes", [0, -1, CHUNK_BYTES + 1])
def test_download_rejects_unbounded_or_nonpositive_chunk_policy(tmp_path: Path, chunk_bytes: int) -> None:
    with pytest.raises(ValueError, match="chunk_bytes"):
        download_external_photo(
            SOURCE,
            DownloadPolicy(POLICY.allowed_hosts, chunk_bytes=chunk_bytes),
            temp_dir=tmp_path,
            opener=lambda *_a, **_k: FakeImageResponse(JPEG_BYTES),
        )

    assert list(tmp_path.iterdir()) == []


def test_oversize_content_length_fails_before_body_read(tmp_path: Path) -> None:
    response = FakeImageResponse(b"", headers={"Content-Length": str(MAX_BYTES + 1)})

    with pytest.raises(PhotoTransferError, match="too large"):
        download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert response.read_calls == 0
    assert list(tmp_path.iterdir()) == []


def test_chunked_stream_crossing_30_mib_is_removed(tmp_path: Path) -> None:
    response = GeneratedImageResponse(MAX_BYTES + 1)

    with pytest.raises(PhotoTransferError, match="too large"):
        download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert max(response.read_sizes) <= CHUNK_BYTES
    assert list(tmp_path.iterdir()) == []


def test_empty_body_is_rejected_without_leaving_temp_file(tmp_path: Path) -> None:
    with pytest.raises(PhotoTransferError, match="empty"):
        download_external_photo(
            SOURCE,
            POLICY,
            temp_dir=tmp_path,
            opener=lambda *_a, **_k: FakeImageResponse(b""),
        )

    assert list(tmp_path.iterdir()) == []


def test_partial_content_length_is_rejected_and_removed(tmp_path: Path) -> None:
    response = FakeImageResponse(JPEG_BYTES, headers={"Content-Length": str(len(JPEG_BYTES) + 10)})

    with pytest.raises(PhotoTransferError, match="partial"):
        download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("declared", ["-1", "not-a-number"])
def test_invalid_content_length_is_rejected_before_body_read(tmp_path: Path, declared: str) -> None:
    response = FakeImageResponse(JPEG_BYTES, headers={"Content-Length": declared})

    with pytest.raises(PhotoTransferError, match="Content-Length"):
        download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert response.read_calls == 0
    assert list(tmp_path.iterdir()) == []


def test_http_redirect_response_is_rejected_without_disclosing_location(tmp_path: Path) -> None:
    response = FakeImageResponse(
        JPEG_BYTES,
        status=302,
        headers={"Location": "https://evil.example/a.jpg?token=redirect-secret"},
    )

    with pytest.raises(PhotoTransferError, match="redirect") as caught:
        download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert "secret" not in str(caught.value)
    assert response.read_calls == 0
    assert list(tmp_path.iterdir()) == []


def test_partial_http_response_is_rejected_before_body_read(tmp_path: Path) -> None:
    response = FakeImageResponse(JPEG_BYTES, status=206)

    with pytest.raises(PhotoTransferError, match="partial"):
        download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert response.read_calls == 0
    assert list(tmp_path.iterdir()) == []


def test_temp_file_is_private_unpredictable_and_exactly_one_per_download(tmp_path: Path) -> None:
    first = download_external_photo(
        SOURCE,
        POLICY,
        temp_dir=tmp_path,
        opener=lambda *_a, **_k: FakeImageResponse(JPEG_BYTES),
    )

    assert list(tmp_path.iterdir()) == [first.path]
    if os.name != "nt":
        assert stat.S_IMODE(first.path.stat().st_mode) & 0o077 == 0
        assert stat.S_IMODE(tmp_path.stat().st_mode) & 0o077 == 0
    assert "photo-secret-id" not in first.path.name
    first_name = first.path.name
    cleanup_download(first)

    second = download_external_photo(
        SOURCE,
        POLICY,
        temp_dir=tmp_path,
        opener=lambda *_a, **_k: FakeImageResponse(JPEG_BYTES),
    )
    assert second.path.name != first_name


def test_base_exception_during_streaming_removes_temp_file(tmp_path: Path) -> None:
    response = FakeImageResponse(JPEG_BYTES, fail_after_reads=1)

    with pytest.raises(KeyboardInterrupt, match="cancel transfer"):
        download_external_photo(SOURCE, POLICY, temp_dir=tmp_path, opener=lambda *_a, **_k: response)

    assert list(tmp_path.iterdir()) == []


def test_base_exception_while_wrapping_temp_descriptor_closes_and_removes_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_fdopen(*_args, **_kwargs):  # noqa: ANN202
        raise KeyboardInterrupt("cancel before streaming")

    monkeypatch.setattr(migration.os, "fdopen", fail_fdopen)

    with pytest.raises(KeyboardInterrupt, match="cancel before streaming"):
        download_external_photo(
            SOURCE,
            POLICY,
            temp_dir=tmp_path,
            opener=lambda *_a, **_k: FakeImageResponse(JPEG_BYTES),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("content", "label"),
    [
        (b"not-an-image", "invalid image"),
        (JPEG_BYTES[:-2], "invalid image"),
        (PNG_BYTES[:-12], "invalid image"),
        (corrupt_png_idat_checksum(PNG_BYTES), "invalid image"),
    ],
    ids=["pillow-open", "jpeg-end-marker", "png-iend", "pillow-verify"],
)
def test_invalid_or_incomplete_image_is_rejected_and_removed(tmp_path: Path, content: bytes, label: str) -> None:
    with pytest.raises(PhotoTransferError, match=label):
        download_external_photo(
            SOURCE,
            POLICY,
            temp_dir=tmp_path,
            opener=lambda *_a, **_k: FakeImageResponse(content),
        )

    assert list(tmp_path.iterdir()) == []


def test_content_type_and_suffix_are_derived_from_file_not_upstream_headers(tmp_path: Path) -> None:
    photo = download_external_photo(
        SOURCE,
        POLICY,
        temp_dir=tmp_path,
        opener=lambda *_a, **_k: FakeImageResponse(
            PNG_BYTES,
            headers={"Content-Type": "image/jpeg; charset=secret"},
        ),
    )

    assert photo.content_type == "image/png"
    assert photo.suffix == ".png"


def test_cleanup_download_unlinks_only_downloaded_file(tmp_path: Path) -> None:
    photo = download_external_photo(
        SOURCE,
        POLICY,
        temp_dir=tmp_path,
        opener=lambda *_a, **_k: FakeImageResponse(JPEG_BYTES),
    )
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")

    cleanup_download(photo)
    cleanup_download(photo)

    assert photo.path.exists() is False
    assert sibling.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://img.example/a.jpg?token=secret#private", "https://img.example/a.jpg"),
        (
            "https://user:password@img.example:8443/a.jpg?X-Amz-Signature=secret#access-token",
            "https://img.example:8443/a.jpg",
        ),
    ],
)
def test_redact_source_url_removes_query_fragment_and_userinfo(url: str, expected: str) -> None:
    assert redact_source_url(url) == expected


class FakeOssError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"OSS error {status} {code}")
        self.status = status
        self.code = code


class FakeHeadResult:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        normalized = {name.lower(): value for name, value in headers.items()}
        self.content_length = int(normalized["content-length"]) if "content-length" in normalized else None
        self.content_type = normalized.get("content-type")


def matching_meta(photo: DownloadedPhoto) -> dict[str, str]:
    return {
        "Content-Length": str(photo.byte_size),
        "x-oss-meta-sha256": photo.sha256,
        "Content-Type": photo.content_type,
    }


class FakeBucket:
    def __init__(
        self,
        *,
        existing_meta: dict[str, str] | None = None,
        initial_head_error: BaseException | None = None,
        put_error: BaseException | None = None,
        appear_on_forbid_overwrite: bool = False,
        appearing_meta: dict[str, str] | None = None,
        after_upload_meta: dict[str, str] | None = None,
        vanish_after_put: bool = False,
    ) -> None:
        self.existing_meta = existing_meta
        self.initial_head_error = initial_head_error
        self.put_error = put_error
        self.appear_on_forbid_overwrite = appear_on_forbid_overwrite
        self.appearing_meta = appearing_meta
        self.after_upload_meta = after_upload_meta
        self.vanish_after_put = vanish_after_put
        self.head_calls: list[str] = []
        self.put_calls: list[tuple[str, Path]] = []
        self.headers: dict[str, str] = {}
        self.overwrite_calls: list[str] = []
        self.delete_calls: list[str] = []

    def head_object(self, key: str) -> FakeHeadResult:
        self.head_calls.append(key)
        if self.initial_head_error is not None and len(self.head_calls) == 1:
            raise self.initial_head_error
        if self.existing_meta is None:
            raise FakeOssError(404, "NoSuchKey")
        return FakeHeadResult(self.existing_meta)

    def put_object_from_file(self, key: str, filename: str, *, headers: dict[str, str]):
        path = Path(filename)
        self.put_calls.append((key, path))
        self.headers = dict(headers)
        if headers.get("x-oss-forbid-overwrite") != "true":
            self.overwrite_calls.append(key)
        if self.appear_on_forbid_overwrite:
            self.existing_meta = self.appearing_meta
            raise FakeOssError(409, "FileAlreadyExists")
        if self.put_error is not None:
            raise self.put_error
        if self.vanish_after_put:
            self.existing_meta = None
        else:
            self.existing_meta = self.after_upload_meta or {
                "Content-Length": str(path.stat().st_size),
                "x-oss-meta-sha256": headers["x-oss-meta-sha256"],
                "Content-Type": headers["Content-Type"],
            }
        return object()

    def delete_object(self, key: str) -> None:
        self.delete_calls.append(key)


@pytest.fixture
def downloaded(tmp_path: Path) -> DownloadedPhoto:
    path = tmp_path / "download.jpg"
    path.write_bytes(JPEG_BYTES)
    return DownloadedPhoto(
        path=path,
        sha256=hashlib.sha256(JPEG_BYTES).hexdigest(),
        byte_size=len(JPEG_BYTES),
        content_type="image/jpeg",
        suffix=".jpg",
    )


def test_matching_content_address_object_is_reused(downloaded: DownloadedPhoto) -> None:
    bucket = FakeBucket(existing_meta={name.lower(): value for name, value in matching_meta(downloaded).items()})

    receipt = store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert receipt.reused is True
    assert receipt.bucket == "bucket"
    assert receipt.key == "content/key.jpg"
    assert bucket.put_calls == []
    assert bucket.delete_calls == []


@pytest.mark.parametrize(
    "existing_meta",
    [
        {"Content-Length": str(len(JPEG_BYTES) + 1), "x-oss-meta-sha256": hashlib.sha256(JPEG_BYTES).hexdigest(), "Content-Type": "image/jpeg"},
        {"Content-Length": str(len(JPEG_BYTES)), "x-oss-meta-sha256": "0" * 64, "Content-Type": "image/jpeg"},
        {"Content-Length": str(len(JPEG_BYTES)), "x-oss-meta-sha256": hashlib.sha256(JPEG_BYTES).hexdigest(), "Content-Type": "image/png"},
    ],
    ids=["size", "sha256", "content-type"],
)
def test_existing_mismatched_object_is_never_overwritten(
    downloaded: DownloadedPhoto,
    existing_meta: dict[str, str],
) -> None:
    bucket = FakeBucket(existing_meta=existing_meta)

    with pytest.raises(OssObjectConflictError):
        store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert bucket.put_calls == []
    assert bucket.delete_calls == []


def test_new_object_uploads_from_file_with_forbid_overwrite_and_is_head_verified(
    downloaded: DownloadedPhoto,
) -> None:
    bucket = FakeBucket()

    receipt = store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert bucket.put_calls == [("content/key.jpg", downloaded.path)]
    assert bucket.headers == {
        "Content-Type": downloaded.content_type,
        "x-oss-meta-sha256": downloaded.sha256,
        "x-oss-forbid-overwrite": "true",
    }
    assert bucket.head_calls == ["content/key.jpg", "content/key.jpg"]
    assert bucket.overwrite_calls == []
    assert bucket.delete_calls == []
    assert receipt.reused is False
    assert receipt.sha256 == downloaded.sha256
    assert receipt.byte_size == downloaded.byte_size
    assert receipt.content_type == downloaded.content_type


def test_object_created_between_head_and_put_is_reused_only_when_exactly_matching(
    downloaded: DownloadedPhoto,
) -> None:
    bucket = FakeBucket(
        appear_on_forbid_overwrite=True,
        appearing_meta=matching_meta(downloaded),
    )

    receipt = store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert receipt.reused is True
    assert bucket.put_calls == [("content/key.jpg", downloaded.path)]
    assert bucket.overwrite_calls == []
    assert bucket.delete_calls == []


def test_concurrently_created_mismatched_object_is_never_overwritten_or_deleted(
    downloaded: DownloadedPhoto,
) -> None:
    mismatched = matching_meta(downloaded)
    mismatched["x-oss-meta-sha256"] = "0" * 64
    bucket = FakeBucket(appear_on_forbid_overwrite=True, appearing_meta=mismatched)

    with pytest.raises(OssObjectConflictError):
        store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert bucket.overwrite_calls == []
    assert bucket.delete_calls == []


def test_object_exists_conflict_without_visible_object_fails_verification(downloaded: DownloadedPhoto) -> None:
    bucket = FakeBucket(appear_on_forbid_overwrite=True, appearing_meta=None)

    with pytest.raises(OssVerificationError, match="missing"):
        store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert bucket.overwrite_calls == []
    assert bucket.delete_calls == []


def test_post_upload_head_mismatch_fails_without_overwrite_or_delete(downloaded: DownloadedPhoto) -> None:
    mismatched = matching_meta(downloaded)
    mismatched["Content-Type"] = "image/png"
    bucket = FakeBucket(after_upload_meta=mismatched)

    with pytest.raises(OssVerificationError):
        store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert len(bucket.put_calls) == 1
    assert bucket.overwrite_calls == []
    assert bucket.delete_calls == []


def test_missing_post_upload_head_fails_without_delete(downloaded: DownloadedPhoto) -> None:
    bucket = FakeBucket(vanish_after_put=True)

    with pytest.raises(OssVerificationError, match="missing"):
        store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert len(bucket.put_calls) == 1
    assert bucket.delete_calls == []


@pytest.mark.parametrize(
    "put_error",
    [
        FakeOssError(400, "ObjectAlreadyExists"),
        FakeOssError(409, "AccessDenied"),
        FakeOssError(403, "AccessDenied"),
        FakeOssError(500, "InternalError"),
        RuntimeError("transport failure"),
    ],
    ids=["wrong-object-code", "wrong-409-code", "auth", "server", "transport"],
)
def test_only_documented_forbid_overwrite_conflict_enters_race_reuse_path(
    downloaded: DownloadedPhoto,
    put_error: BaseException,
) -> None:
    bucket = FakeBucket(put_error=put_error)

    with pytest.raises(type(put_error)) as caught:
        store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert caught.value is put_error
    assert bucket.head_calls == ["content/key.jpg"]
    assert bucket.overwrite_calls == []
    assert bucket.delete_calls == []


@pytest.mark.parametrize(
    "head_error",
    [FakeOssError(403, "AccessDenied"), FakeOssError(500, "InternalError"), RuntimeError("transport failure")],
    ids=["auth", "server", "transport"],
)
def test_initial_head_transport_auth_or_server_failure_never_uploads(
    downloaded: DownloadedPhoto,
    head_error: BaseException,
) -> None:
    bucket = FakeBucket(initial_head_error=head_error)

    with pytest.raises(type(head_error)) as caught:
        store_downloaded_photo(bucket, "bucket", "content/key.jpg", downloaded)

    assert caught.value is head_error
    assert bucket.put_calls == []
    assert bucket.delete_calls == []
