from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from io import StringIO
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select

from app.core.config import settings
from scripts import build_oss_export_manifest as manifest
from scripts.build_oss_export_manifest import (
    ManifestScope,
    UnsupportedPhotoStorageError,
    iter_manifest_rows,
    load_scope_payloads,
    require_sha256,
)


CATEGORIES = ("before_box", "collector_barcode", "module_meter", "after_box")


class MappingResult:
    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._rows = list(rows)

    def mappings(self) -> list[Mapping[str, Any]]:
        return self._rows


class RecordingSession:
    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self.rows = list(rows)
        self.statements: list[Any] = []
        self.dirty: set[Any] = set()
        self.new: set[Any] = set()

    def execute(self, statement: Any) -> MappingResult:
        self.statements.append(statement)
        if len(self.statements) == 1:
            assert str(statement).strip() == "SET TRANSACTION READ ONLY"
            return MappingResult(())
        if len(self.statements) == 2:
            assert isinstance(statement, Select)
            return MappingResult(self.rows)
        pytest.fail("manifest loader issued more than one SELECT")

    def add(self, _value: Any) -> None:
        pytest.fail("read-only manifest must not add ORM objects")

    def flush(self) -> None:
        pytest.fail("read-only manifest must not flush")

    def commit(self) -> None:
        pytest.fail("read-only manifest must not commit")


def photo_rows(
    group_id: str,
    *,
    group_pk: str | None = None,
    terminal: str = "T01",
    task_id: int = 7,
    archive_status: str = "archived",
    auto_archive_status: str = "",
    storage_type: str = "oss",
    storage_bucket: str = "export-bucket",
) -> list[dict[str, Any]]:
    del task_id  # The scalar result does not include the filter-only task column.
    primary_key = group_pk or f"pk-{group_id}"
    rows: list[dict[str, Any]] = []
    for index, category in enumerate(CATEGORIES, start=1):
        rows.append(
            {
                "group_pk": primary_key,
                "group_id": group_id,
                "terminal": terminal,
                "display_meter_no": f"meter-{group_id}",
                "installation_address": f"address-{group_id}",
                "status": "approved",
                "archive_status": archive_status,
                "archived_at": None,
                "auto_archive_status": auto_archive_status,
                "photo_pk": f"photo-pk-{group_id}-{index}",
                "photo_legacy_id": f"photo-{group_id}-{index}",
                "upload_status": "uploaded",
                "category": category,
                "photo_archive_status": archive_status,
                "asset_no": f"module-{group_id}",
                "collector": f"collector-{group_id}",
                "image_url": f"oss://{storage_bucket}/photos/{group_id}/{index}.jpg",
                "original_filename": f"capture-{index}.jpg",
                "storage_type": storage_type,
                "storage_bucket": storage_bucket,
                "storage_key": f"photos/{group_id}/{index}.jpg",
                "sha256": f"{index:x}" * 64,
                "byte_size": index * 100,
                "content_type": "image/jpeg",
                "sort_order": index,
            }
        )
    return rows


def test_load_scope_payloads_sets_read_only_and_selects_only_ordered_scalar_columns() -> None:
    session = RecordingSession(photo_rows("group-a"))
    scope = ManifestScope(
        "team-1",
        task_id=7,
        terminal="T01",
        group_ids=("group-a", "group-b"),
    )

    payloads = load_scope_payloads(session, scope)

    assert len(session.statements) == 2
    statement = session.statements[1]
    assert [column.key for column in statement.selected_columns] == [
        "group_pk",
        "group_id",
        "terminal",
        "display_meter_no",
        "installation_address",
        "status",
        "archive_status",
        "archived_at",
        "auto_archive_status",
        "photo_pk",
        "photo_legacy_id",
        "upload_status",
        "category",
        "photo_archive_status",
        "asset_no",
        "collector",
        "image_url",
        "original_filename",
        "storage_type",
        "storage_bucket",
        "storage_key",
        "sha256",
        "byte_size",
        "content_type",
        "sort_order",
    ]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "material_groups.raw_data AS raw_data" not in sql
    assert "photos.raw_data" not in sql
    assert "material_groups.team_id = 'team-1'" in sql
    assert "material_groups.legacy_task_id = 7" in sql
    assert "material_groups.terminal = 'T01'" in sql
    assert "material_groups.legacy_id IN ('group-a', 'group-b')" in sql
    assert "photos.is_active IS true" in sql
    assert "ORDER BY material_groups.legacy_id, material_groups.id, photos.sort_order, photos.id" in sql
    assert payloads[0]["id"] == "group-a"
    assert payloads[0]["photos"][0]["id"] == "photo-group-a-1"


def test_manifest_validates_every_photo_before_header_then_signs_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    session = RecordingSession(photo_rows("group-a"))
    signed: list[tuple[str, int]] = []
    rows = iter_manifest_rows(
        session,
        ManifestScope("team-1", terminal="T01", archived_only=True),
        lambda key, ttl: signed.append((key, ttl)) or f"https://signed.invalid/{key}",
    )

    header = next(rows)

    assert header == {
        "schema": "module-manager-oss-export/v1",
        "kind": "manifest",
        "planned_count": 4,
        "planned_bytes": 1000,
    }
    assert signed == []
    first = next(rows)
    assert signed == [("photos/group-a/1.jpg", 300)]
    assert first == {
        "schema": "module-manager-oss-export/v1",
        "kind": "item",
        "group_id": "group-a",
        "photo_id": "photo-group-a-1",
        "category": "before_box",
        "relative_path": "T01/meter-group-a-module-group-a-address-group-a/module-group-a-表箱整体改造前.jpg",
        "storage_bucket": "export-bucket",
        "storage_key": "photos/group-a/1.jpg",
        "sha256": "1" * 64,
        "byte_size": 100,
        "content_type": "image/jpeg",
        "download_url": "https://signed.invalid/photos/group-a/1.jpg",
    }
    remaining = list(rows)
    assert [key for key, _ttl in signed] == [f"photos/group-a/{index}.jpg" for index in range(1, 5)]
    assert len(remaining) == 3
    assert session.dirty == set()
    assert session.new == set()


def test_manifest_refuses_external_storage_before_header_or_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    rows = photo_rows("group-a")
    rows[2]["storage_type"] = "external_url"
    signed: list[str] = []

    with pytest.raises(UnsupportedPhotoStorageError) as captured:
        list(
            iter_manifest_rows(
                RecordingSession(rows),
                ManifestScope("team-1"),
                lambda key, _ttl: signed.append(key) or "must-not-sign",
            )
        )

    assert captured.value.counts == {"external_url": 1}
    assert signed == []


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("storage_bucket", "", {"missing_storage_bucket": 1}),
        ("storage_bucket", "wrong-bucket", {"wrong_storage_bucket": 1}),
        ("storage_key", "", {"missing_storage_key": 1}),
        ("byte_size", 0, {"invalid_byte_size": 1}),
        ("sha256", "", {"invalid_sha256": 1}),
        ("sha256", "g" * 64, {"invalid_sha256": 1}),
    ],
)
def test_manifest_rejects_incomplete_oss_metadata_before_signing(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
    expected: dict[str, int],
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    rows = photo_rows("group-a")
    rows[0][field] = value
    signed: list[str] = []

    with pytest.raises(UnsupportedPhotoStorageError) as captured:
        list(
            iter_manifest_rows(
                RecordingSession(rows),
                ManifestScope("team-1"),
                lambda key, _ttl: signed.append(key) or "must-not-sign",
            )
        )

    assert captured.value.counts == expected
    assert signed == []


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("storage_bucket", " export-bucket", {"wrong_storage_bucket": 1}),
        ("storage_bucket", "export-bucket ", {"wrong_storage_bucket": 1}),
        ("storage_key", " photos/group-a/1.jpg", {"invalid_storage_key": 1}),
        ("storage_key", "photos/group-a/1.jpg ", {"invalid_storage_key": 1}),
        ("sha256", f" {'1' * 64}", {"invalid_sha256": 1}),
        ("sha256", f"{'1' * 64} ", {"invalid_sha256": 1}),
    ],
    ids=(
        "bucket-leading",
        "bucket-trailing",
        "key-leading",
        "key-trailing",
        "sha-leading",
        "sha-trailing",
    ),
)
def test_manifest_rejects_noncanonical_oss_metadata_before_any_output(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    expected: dict[str, int],
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    rows = photo_rows("group-a")
    rows[0][field] = value
    original_storage_key = rows[0]["storage_key"]
    signed: list[str] = []
    emitted: list[dict[str, Any]] = []
    iterator = iter_manifest_rows(
        RecordingSession(rows),
        ManifestScope("team-1"),
        lambda key, _ttl: signed.append(key) or "must-not-sign",
    )

    with pytest.raises(UnsupportedPhotoStorageError) as captured:
        while True:
            emitted.append(next(iterator))

    assert captured.value.counts == expected
    assert emitted == []
    assert signed == []
    assert rows[0]["storage_key"] == original_storage_key
    assert rows[0][field] == value


def test_manifest_filters_unarchived_groups_before_planning_and_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    rows = photo_rows("group-b", archive_status="pending") + photo_rows("group-a")
    signed: list[str] = []

    output = list(
        iter_manifest_rows(
            RecordingSession(rows),
            ManifestScope("team-1", archived_only=True),
            lambda key, _ttl: signed.append(key) or f"signed:{key}",
        )
    )

    assert output[0]["planned_count"] == 4
    assert {item["group_id"] for item in output[1:]} == {"group-a"}
    assert signed == [f"photos/group-a/{index}.jpg" for index in range(1, 5)]


def test_manifest_item_order_is_stable_for_reordered_groups_and_photos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    rows = photo_rows("group-b") + photo_rows("group-a")
    reordered = list(reversed(rows))

    first = list(iter_manifest_rows(RecordingSession(rows), ManifestScope("team-1"), lambda key, _ttl: key))
    second = list(
        iter_manifest_rows(RecordingSession(reordered), ManifestScope("team-1"), lambda key, _ttl: key)
    )

    first_items = [(item["group_id"], item["category"], item["relative_path"]) for item in first[1:]]
    second_items = [(item["group_id"], item["category"], item["relative_path"]) for item in second[1:]]
    assert first_items == second_items
    assert [(group_id, category) for group_id, category, _path in first_items] == [
        (group_id, category)
        for group_id in ("group-a", "group-b")
        for category in CATEGORIES
    ]


@pytest.mark.parametrize("expires_seconds", [59, 601])
def test_manifest_rejects_ttl_outside_the_signed_url_window(expires_seconds: int) -> None:
    session = RecordingSession(photo_rows("group-a"))

    with pytest.raises(ValueError, match="between 60 and 600"):
        list(
            iter_manifest_rows(
                session,
                ManifestScope("team-1"),
                lambda _key, _ttl: "must-not-sign",
                expires_seconds=expires_seconds,
            )
        )

    assert session.statements == []


@pytest.mark.parametrize("expires_seconds", [60, 600])
def test_manifest_accepts_ttl_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    expires_seconds: int,
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    signed: list[tuple[str, int]] = []

    list(
        iter_manifest_rows(
            RecordingSession(photo_rows("group-a")),
            ManifestScope("team-1"),
            lambda key, ttl: signed.append((key, ttl)) or key,
            expires_seconds=expires_seconds,
        )
    )

    assert signed == [(f"photos/group-a/{index}.jpg", expires_seconds) for index in range(1, 5)]


def test_require_sha256_accepts_only_full_hex_and_normalizes_case() -> None:
    assert require_sha256("A0" * 32) == "a0" * 32
    for invalid in ("", "a" * 63, "a" * 65, "z" * 64, f" {'a' * 64}", f"{'a' * 64} "):
        with pytest.raises(ValueError, match="SHA256"):
            require_sha256(invalid)


def test_cli_writes_url_free_header_and_uses_key_only_oss_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    session = RecordingSession(photo_rows("group-a"))

    class SessionContext:
        def __enter__(self) -> RecordingSession:
            return session

        def __exit__(self, *_args: Any) -> None:
            return None

    class Bucket:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int, bool]] = []

        def sign_url(self, method: str, key: str, ttl: int, *, slash_safe: bool) -> str:
            self.calls.append((method, key, ttl, slash_safe))
            return f"https://signed.invalid/{key}"

    bucket = Bucket()
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(manifest, "SessionLocal", SessionContext)
    monkeypatch.setattr(manifest, "require_oss_client", lambda: bucket)
    monkeypatch.setattr(manifest.sys, "stdout", stdout)
    monkeypatch.setattr(manifest.sys, "stderr", stderr)

    result = manifest.main(["--team-id", "team-1", "--expires-seconds", "60"])

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert result == 0
    assert lines[0] == {
        "schema": "module-manager-oss-export/v1",
        "kind": "manifest",
        "planned_count": 4,
        "planned_bytes": 1000,
    }
    assert "download_url" not in lines[0]
    assert bucket.calls == [
        ("GET", f"photos/group-a/{index}.jpg", 60, True)
        for index in range(1, 5)
    ]
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("storage_type", ("OSS", " oss", "oss "))
def test_cli_rejects_noncanonical_storage_type_before_stdout_or_signing(
    monkeypatch: pytest.MonkeyPatch,
    storage_type: str,
) -> None:
    monkeypatch.setattr(settings, "oss_bucket", "export-bucket")
    session = RecordingSession(photo_rows("group-a", storage_type=storage_type))

    class SessionContext:
        def __enter__(self) -> RecordingSession:
            return session

        def __exit__(self, *_args: Any) -> None:
            return None

    class Bucket:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int, bool]] = []

        def sign_url(self, method: str, key: str, ttl: int, *, slash_safe: bool) -> str:
            self.calls.append((method, key, ttl, slash_safe))
            return f"https://signed.invalid/{key}"

    bucket = Bucket()
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(manifest, "SessionLocal", SessionContext)
    monkeypatch.setattr(manifest, "require_oss_client", lambda: bucket)
    monkeypatch.setattr(manifest.sys, "stdout", stdout)
    monkeypatch.setattr(manifest.sys, "stderr", stderr)

    result = manifest.main(["--team-id", "team-1"])

    assert result == 2
    assert stdout.getvalue() == ""
    assert bucket.calls == []
    assert json.loads(stderr.getvalue())["counts"] == {storage_type: 4}


def test_cli_does_not_accept_an_output_report_argument() -> None:
    with pytest.raises(SystemExit) as captured:
        manifest.parse_args(["--team-id", "team-1", "--output-report", "report.json"])

    assert captured.value.code == 2
