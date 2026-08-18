from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from scripts import migrate_external_photos_to_oss as migration
from scripts.migrate_external_photos_to_oss import parse_args
from app.services.external_photo_oss_migration import DownloadedPhoto, OssObjectReceipt


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_external_photos_to_oss.py"
LEGACY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_photos_to_oss.py"


def test_cli_requires_an_explicit_safe_mode() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "one of the arguments --dry-run --execute --resume --rollback-run is required" in result.stderr


def test_legacy_entrypoint_exits_with_retirement_guidance_before_parsing() -> None:
    result = subprocess.run(
        [sys.executable, str(LEGACY_SCRIPT), "--retired-probe"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "This migration entry is retired. Use migrate_external_photos_to_oss.py "
        "with an explicit mode, migration id, and source-host allowlist."
    ) in result.stderr


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--execute"],
        ["--execute", "--migration-id", "run-1", "--max-workers", "2"],
    ],
)
def test_unsafe_invocations_are_rejected(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(argv)


@pytest.mark.parametrize("mode", ["--execute", "--resume"])
def test_execute_and_resume_require_allowlist_file(mode: str) -> None:
    with pytest.raises(SystemExit, match="allowlist"):
        parse_args([mode, "--migration-id", "run-1"])


@pytest.mark.parametrize(
    "argv",
    [
        ["--dry-run", "--limit", "1"],
        ["--rollback-run", "run-1", "--limit", "1"],
        ["--execute", "--migration-id", "run-1", "--allowlist-file", "hosts.txt", "--limit", "0"],
        ["--resume", "--migration-id", "run-1", "--allowlist-file", "hosts.txt", "--limit", "-1"],
    ],
)
def test_limit_is_positive_and_only_valid_for_execute_or_resume(argv: list[str]) -> None:
    with pytest.raises(SystemExit, match="limit"):
        parse_args(argv)


def test_candidate_is_immutable_and_statement_has_stable_scalar_order() -> None:
    photo_id = uuid4()
    group_id = uuid4()
    candidate = migration.ExternalPhotoCandidate(
        photo_id=photo_id,
        team_id="team-a",
        group_id=group_id,
        group_legacy_id="group-1",
        url="https://img.example/a.jpg?token=secret",
        declared_sha256="",
        filename="a.jpg",
    )

    with pytest.raises(FrozenInstanceError):
        candidate.url = "https://changed.example/a.jpg"  # type: ignore[misc]

    sql = str(migration.candidate_statement("team-a", 3).compile(dialect=postgresql.dialect()))
    assert "photos.raw_data" not in sql
    assert "photos.team_id =" in sql
    assert "LIMIT" in sql
    assert (
        "ORDER BY photos.team_id ASC, material_groups.legacy_id ASC, "
        "photos.sort_order ASC, photos.id ASC"
    ) in sql


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DryRunSession:
    def __init__(self, candidate_rows, storage_rows):
        self.candidate_rows = candidate_rows
        self.storage_rows = storage_rows
        self.rolled_back = False

    def execute(self, statement):
        sql = str(statement)
        if sql.startswith("SET TRANSACTION"):
            return _Rows([])
        if "GROUP BY photos.storage_type" in sql:
            return _Rows(self.storage_rows)
        return _Rows(self.candidate_rows)

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        raise AssertionError("dry-run committed")


def test_dry_run_is_database_read_only_and_does_not_transfer(monkeypatch) -> None:
    group_id = uuid4()
    rows = [
        SimpleNamespace(
            photo_id=uuid4(),
            team_id="team-a",
            group_id=group_id,
            group_legacy_id="group-1",
            url="https://img.example/a.jpg?token=secret",
            declared_sha256="",
            filename="a.jpg",
            sort_order=0,
        ),
        SimpleNamespace(
            photo_id=uuid4(),
            team_id="team-a",
            group_id=group_id,
            group_legacy_id="group-1",
            url="https://img.example/b.jpg",
            declared_sha256="f" * 64,
            filename="b.jpg",
            sort_order=1,
        ),
    ]
    session = _DryRunSession(rows, [("external_url", 2), ("mystery", 1)])
    monkeypatch.setattr(migration, "validate_remote_image_url", lambda *_args, **_kwargs: ("203.0.113.10",))
    monkeypatch.setattr(
        migration,
        "download_external_photo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("downloaded")),
    )
    monkeypatch.setattr(
        migration,
        "store_downloaded_photo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("uploaded")),
    )

    report = migration.run_dry_run(session, team_id="", allowlist=None)

    assert report["external_url_candidates"] == 2
    assert report["unknown_storage"] == 1
    assert report["source_hosts"] == {"img.example": 2}
    assert "token=secret" not in json.dumps(report)
    assert session.rolled_back is True


def test_start_gate_requires_memory_disk_health_and_no_new_oom() -> None:
    with pytest.raises(migration.ResourceGateError, match="400 MiB"):
        migration.start_gate(migration.ResourceSnapshot(399 * migration.MIB, 600 * migration.MIB, True, "cursor-1"))
    with pytest.raises(migration.ResourceGateError, match="512 MiB"):
        migration.start_gate(migration.ResourceSnapshot(500 * migration.MIB, 511 * migration.MIB, True, "cursor-1"))
    with pytest.raises(migration.ResourceGateError, match="health"):
        migration.start_gate(migration.ResourceSnapshot(500 * migration.MIB, 600 * migration.MIB, False, "cursor-1"))


@pytest.mark.parametrize(
    ("snapshot", "errors", "reason"),
    [
        ((249, 600, True, "cursor-1"), 0, "low_memory"),
        ((500, 600, False, "cursor-1"), 0, "health_failed"),
        ((500, 600, True, "cursor-2"), 0, "new_oom"),
        ((500, 600, True, "cursor-1"), 5, "oss_error_limit"),
    ],
)
def test_runtime_stop_reasons(snapshot: tuple[int, int, bool, str], errors: int, reason: str) -> None:
    mem_mib, disk_mib, healthy, marker = snapshot
    resource = migration.ResourceSnapshot(
        mem_mib * migration.MIB,
        disk_mib * migration.MIB,
        healthy,
        marker,
    )
    assert migration.stop_reason(resource, "cursor-1", errors) == reason


def test_report_redacts_query_and_is_owner_only(tmp_path: Path) -> None:
    report = {
        "items": {
            "photo-1": {
                "source_url": "https://user:password@img.example/a.jpg?token=secret#fragment",
                "error": "failed https://img.example/a.jpg?token=secret",
            }
        }
    }

    path = migration.write_report(tmp_path / "run.json", report)
    content = path.read_text(encoding="utf-8")

    assert "token=secret" not in content
    assert "password" not in content
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def _candidate(*, declared: str = "", url: str = "https://img.example/photo.jpg?token=secret"):
    return migration.ExternalPhotoCandidate(
        photo_id=uuid4(),
        team_id="team-a",
        group_id=uuid4(),
        group_legacy_id="group-1",
        url=url,
        declared_sha256=declared,
        filename="photo.jpg",
    )


def _install_safe_run_boundaries(monkeypatch, tmp_path: Path, candidates) -> None:
    temp_dir = tmp_path / "private-run"
    temp_dir.mkdir(mode=0o700)
    monkeypatch.setattr(migration, "_new_run_temp_directory", lambda _migration_id: temp_dir)
    monkeypatch.setattr(migration, "_close_run_temp_directory", lambda _path: None)
    monkeypatch.setattr(migration, "_fetch_candidates", lambda *_args, **_kwargs: list(candidates))
    monkeypatch.setattr(
        migration,
        "probe_resources",
        lambda _path: migration.ResourceSnapshot(500 * migration.MIB, 600 * migration.MIB, True, "cursor-1"),
    )
    monkeypatch.setattr(migration, "_database_counts", lambda _factory: (0, 0))
    monkeypatch.setattr(migration, "oss_object_key", lambda *_args, **_kwargs: "content/photo.jpg")
    monkeypatch.setattr(migration, "cleanup_download", lambda photo: photo.path.unlink(missing_ok=True))


@pytest.mark.parametrize(
    ("declared_kind", "expected"),
    [
        ("empty", "committed"),
        ("url", "committed"),
        ("content", "committed"),
        ("mismatch", "declared_hash_mismatch"),
        ("invalid", "invalid_declared_hash"),
    ],
)
def test_declared_hash_policy(monkeypatch, tmp_path: Path, declared_kind: str, expected: str) -> None:
    content_sha256 = "a" * 64
    url = "https://img.example/photo.jpg?token=secret"
    declared = {
        "empty": "",
        "url": __import__("hashlib").sha256(url.encode()).hexdigest(),
        "content": content_sha256,
        "mismatch": "f" * 64,
        "invalid": "legacy-hash",
    }[declared_kind]
    candidate = _candidate(declared=declared, url=url)
    _install_safe_run_boundaries(monkeypatch, tmp_path, [candidate])

    def download(*_args, temp_dir: Path, **_kwargs):
        path = temp_dir / "download.jpg"
        path.write_bytes(b"image")
        return DownloadedPhoto(path, content_sha256, 5, "image/jpeg", ".jpg")

    store_calls = []

    def store(_bucket, bucket_name, key, photo):
        store_calls.append((bucket_name, key))
        return OssObjectReceipt(bucket_name, key, photo.sha256, photo.byte_size, photo.content_type, False)

    monkeypatch.setattr(migration, "download_external_photo", download)
    monkeypatch.setattr(migration, "store_downloaded_photo", store)
    monkeypatch.setattr(
        migration,
        "_commit_group",
        lambda *_args, **_kwargs: {
            "statuses": {str(candidate.photo_id): "committed"},
            "group_status": "approved",
            "final_delivery_ready": True,
        },
    )

    report = migration.execute_run(
        lambda: None,
        SimpleNamespace(bucket_name="bucket-a"),
        migration_id="run-1",
        allowlist=frozenset({"img.example"}),
    )

    assert report["items"][str(candidate.photo_id)]["status"] == expected
    assert "token=secret" not in json.dumps(report)
    assert bool(store_calls) is (expected == "committed")


def test_group_transfers_finish_before_short_commit_and_only_one_file_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    group_id = uuid4()
    candidates = [
        migration.ExternalPhotoCandidate(
            uuid4(),
            "team-a",
            group_id,
            "group-1",
            f"https://img.example/{index}.jpg",
            "",
            f"{index}.jpg",
        )
        for index in range(2)
    ]
    _install_safe_run_boundaries(monkeypatch, tmp_path, candidates)
    events: list[str] = []

    def download(source, _policy, *, temp_dir):
        assert list(temp_dir.iterdir()) == []
        events.append(f"download:{source.photo_id}")
        path = temp_dir / f"{source.photo_id}.jpg"
        path.write_bytes(b"image")
        return DownloadedPhoto(path, str(source.photo_id).replace("-", "")[:32] * 2, 5, "image/jpeg", ".jpg")

    monkeypatch.setattr(migration, "download_external_photo", download)
    monkeypatch.setattr(
        migration,
        "store_downloaded_photo",
        lambda _bucket, bucket_name, key, photo: OssObjectReceipt(
            bucket_name, key, photo.sha256, photo.byte_size, photo.content_type, False
        ),
    )

    def commit(_factory, *, transfers, **_kwargs):
        events.append("commit")
        assert len(transfers) == 2
        return {
            "statuses": {str(item.candidate.photo_id): "committed" for item in transfers},
            "group_status": "approved",
            "final_delivery_ready": True,
        }

    monkeypatch.setattr(migration, "_commit_group", commit)

    report = migration.execute_run(
        lambda: None,
        SimpleNamespace(bucket_name="bucket-a"),
        migration_id="run-1",
        allowlist=frozenset({"img.example"}),
    )

    assert events[-1] == "commit"
    assert events.count("commit") == 1
    assert report["committed"] == 2


class _Begin:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        self.session.in_transaction = True
        return self

    def __exit__(self, exc_type, _exc, _tb):
        self.session.in_transaction = False
        return False


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class _CommitSession:
    def __init__(self, group, photos):
        self.group = group
        self.photos = photos
        self.in_transaction = False
        self.lock_statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def begin(self):
        return _Begin(self)

    def scalar(self, statement):
        assert self.in_transaction
        self.lock_statements.append(statement)
        return self.group

    def scalars(self, statement):
        assert self.in_transaction
        self.lock_statements.append(statement)
        return _Scalars(self.photos)

    def flush(self):
        assert self.in_transaction


def _photo_for(candidate, *, image_url: str | None = None, sha256: str | None = None):
    return SimpleNamespace(
        id=candidate.photo_id,
        team_id=candidate.team_id,
        group_id=candidate.group_id,
        is_active=True,
        image_url=image_url if image_url is not None else candidate.url,
        storage_type="external_url",
        storage_bucket=None,
        storage_key=None,
        object_key="legacy/object",
        sha256=sha256 if sha256 is not None else candidate.declared_sha256,
        content_type=None,
        byte_size=None,
        raw_data={},
    )


def _transfer_for(candidate, *, sha256: str = "a" * 64, reused: bool = False):
    receipt = OssObjectReceipt("bucket-a", "content/photo.jpg", sha256, 5, "image/jpeg", reused)
    return migration.PreparedTransfer(candidate, receipt)


def test_locked_commit_rechecks_source_records_complete_audit_and_invalidates_once(monkeypatch) -> None:
    candidate = _candidate(declared="")
    group = SimpleNamespace(id=candidate.group_id, team_id="team-a", legacy_id="group-1", status="approved")
    photo = _photo_for(candidate)
    session = _CommitSession(group, [photo])
    invalidations = []
    monkeypatch.setattr(
        migration,
        "invalidate_verification_for_group",
        lambda current, locked_group, actor, reason: invalidations.append(
            (current, locked_group, actor, reason)
        ),
    )

    result = migration._commit_group(
        lambda: session,
        group_id=candidate.group_id,
        transfers=[_transfer_for(candidate)],
        migration_id="run-1",
    )

    assert result["statuses"][str(candidate.photo_id)] == "committed"
    assert len(invalidations) == 1
    assert invalidations[0][2:] == ("oss-migration", "external_photo_migrated_to_oss")
    assert all(statement._for_update_arg is not None for statement in session.lock_statements)
    assert photo.image_url == "oss://bucket-a/content/photo.jpg"
    assert {
        "pre_oss_image_url",
        "pre_oss_storage_type",
        "pre_oss_storage_bucket",
        "pre_oss_storage_key",
        "pre_oss_object_key",
        "pre_oss_sha256",
        "pre_oss_content_type",
        "pre_oss_byte_size",
        "pre_oss_source_type",
        "oss_migration_id",
        "oss_synced_at",
    } <= photo.raw_data.keys()


def test_concurrent_source_change_is_not_overwritten(monkeypatch) -> None:
    candidate = _candidate()
    group = SimpleNamespace(id=candidate.group_id, team_id="team-a", legacy_id="group-1", status="approved")
    photo = _photo_for(candidate, image_url="https://new.example/photo.jpg")
    session = _CommitSession(group, [photo])
    monkeypatch.setattr(
        migration,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalidated conflict")),
    )

    result = migration._commit_group(
        lambda: session,
        group_id=candidate.group_id,
        transfers=[_transfer_for(candidate)],
        migration_id="run-1",
    )

    assert result["statuses"][str(candidate.photo_id)] == "conflict"
    assert photo.image_url == "https://new.example/photo.jpg"


def test_duplicate_content_is_reported_before_unique_constraint(monkeypatch) -> None:
    candidate = _candidate()
    duplicate_sha = "a" * 64
    group = SimpleNamespace(id=candidate.group_id, team_id="team-a", legacy_id="group-1", status="approved")
    target = _photo_for(candidate)
    existing = SimpleNamespace(id=uuid4(), sha256=duplicate_sha)
    session = _CommitSession(group, [target, existing])
    monkeypatch.setattr(
        migration,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalidated duplicate")),
    )

    result = migration._commit_group(
        lambda: session,
        group_id=candidate.group_id,
        transfers=[_transfer_for(candidate, sha256=duplicate_sha)],
        migration_id="run-1",
    )

    assert result["statuses"][str(candidate.photo_id)] == "duplicate_content"
    assert target.storage_type == "external_url"


def test_resume_reuses_uploaded_object_after_precommit_failure(monkeypatch, tmp_path: Path) -> None:
    candidate = _candidate()
    _install_safe_run_boundaries(monkeypatch, tmp_path, [candidate])
    object_exists = False

    def download(*_args, temp_dir: Path, **_kwargs):
        path = temp_dir / "download.jpg"
        path.write_bytes(b"image")
        return DownloadedPhoto(path, "a" * 64, 5, "image/jpeg", ".jpg")

    def store(_bucket, bucket_name, key, photo):
        nonlocal object_exists
        reused = object_exists
        object_exists = True
        return OssObjectReceipt(bucket_name, key, photo.sha256, photo.byte_size, photo.content_type, reused)

    commit_attempts = 0

    def commit(*_args, **_kwargs):
        nonlocal commit_attempts
        commit_attempts += 1
        if commit_attempts == 1:
            raise RuntimeError("precommit crash")
        return {
            "statuses": {str(candidate.photo_id): "committed"},
            "group_status": "approved",
            "final_delivery_ready": True,
        }

    monkeypatch.setattr(migration, "download_external_photo", download)
    monkeypatch.setattr(migration, "store_downloaded_photo", store)
    monkeypatch.setattr(migration, "_commit_group", commit)
    first = migration.execute_run(
        lambda: None,
        SimpleNamespace(bucket_name="bucket-a"),
        migration_id="run-1",
        allowlist=frozenset({"img.example"}),
    )
    second = migration.resume_run(
        lambda: None,
        SimpleNamespace(bucket_name="bucket-a"),
        migration_id="run-1",
        allowlist=frozenset({"img.example"}),
    )

    assert first["failed"] == 1
    assert second["reused_objects"] == 1
    assert second["committed"] == 1


def test_resource_stop_preserves_migration_id_and_exact_counters(monkeypatch, tmp_path: Path) -> None:
    candidates = [_candidate(), _candidate(url="https://img.example/second.jpg")]
    _install_safe_run_boundaries(monkeypatch, tmp_path, candidates)
    probes = iter(
        [
            migration.ResourceSnapshot(500 * migration.MIB, 600 * migration.MIB, True, "cursor-1"),
            migration.ResourceSnapshot(249 * migration.MIB, 600 * migration.MIB, True, "cursor-1"),
        ]
    )
    monkeypatch.setattr(migration, "probe_resources", lambda _path: next(probes))
    monkeypatch.setattr(
        migration,
        "download_external_photo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("downloaded after stop")),
    )

    report = migration.execute_run(
        lambda: None,
        SimpleNamespace(bucket_name="bucket-a"),
        migration_id="run-1",
        allowlist=frozenset({"img.example"}),
    )

    assert report["migration_id"] == "run-1"
    assert report["stop_reason"] == "low_memory"
    assert report["candidate_count"] == 2
    assert set(
        (
            "uploaded",
            "reused_objects",
            "committed",
            "failed",
            "conflicts",
            "byte_count",
            "remaining_external_url",
            "unknown_storage",
            "failure_counts",
        )
    ) <= report.keys()


def test_rollback_restores_database_only_and_invalidates_each_changed_group_once(monkeypatch) -> None:
    group_id = uuid4()
    photo = SimpleNamespace(
        id=uuid4(),
        team_id="team-a",
        group_id=group_id,
        image_url="oss://bucket-a/content/photo.jpg",
        storage_type="oss",
        storage_bucket="bucket-a",
        storage_key="content/photo.jpg",
        object_key="content/photo.jpg",
        sha256="a" * 64,
        content_type="image/jpeg",
        byte_size=5,
        raw_data={
            "pre_oss_image_url": "https://img.example/photo.jpg?token=secret",
            "pre_oss_storage_type": "external_url",
            "pre_oss_storage_bucket": None,
            "pre_oss_storage_key": None,
            "pre_oss_object_key": "legacy/object",
            "pre_oss_sha256": "",
            "pre_oss_content_type": None,
            "pre_oss_byte_size": None,
            "oss_migration_id": "run-1",
            "oss_migration_bucket": "bucket-a",
            "oss_migration_key": "content/photo.jpg",
            "oss_migration_sha256": "a" * 64,
        },
    )
    group = SimpleNamespace(id=group_id, team_id="team-a", legacy_id="group-1", status="approved")
    session = _CommitSession(group, [photo])
    invalidations = []
    monkeypatch.setattr(
        migration,
        "_fetch_rollback_candidates",
        lambda *_args, **_kwargs: [migration.RollbackCandidate(photo.id, group_id)],
    )
    monkeypatch.setattr(migration, "_database_counts", lambda _factory: (1, 0))
    monkeypatch.setattr(
        migration,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: invalidations.append("invalidated"),
    )

    report = migration.rollback_run(lambda: session, migration_id="run-1")

    assert report["rolled_back"] == 1
    assert photo.storage_type == "external_url"
    assert photo.image_url == "https://img.example/photo.jpg?token=secret"
    assert "oss_rollback_at" in photo.raw_data
    assert invalidations == ["invalidated"]


def test_main_execute_uses_application_session_factory_and_writes_report(monkeypatch, tmp_path: Path) -> None:
    allowlist = tmp_path / "hosts.txt"
    allowlist.write_text("img.example\n", encoding="utf-8")
    report_path = tmp_path / "execute.json"
    bucket = object()
    captured = {}
    monkeypatch.setattr(migration, "require_oss_client", lambda: bucket)

    def execute(factory, selected_bucket, **kwargs):
        captured.update(factory=factory, bucket=selected_bucket, **kwargs)
        return {
            "failed": 0,
            "stop_reason": "",
            "candidate_count": 0,
            "items": {},
        }

    monkeypatch.setattr(migration, "execute_run", execute)

    exit_code = migration.main(
        [
            "--execute",
            "--migration-id",
            "run-1",
            "--allowlist-file",
            str(allowlist),
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 0
    assert captured == {
        "factory": migration.SessionLocal,
        "bucket": bucket,
        "migration_id": "run-1",
        "allowlist": frozenset({"img.example"}),
        "limit": 0,
    }
    assert report_path.exists()


def test_main_rollback_never_initializes_oss(monkeypatch, tmp_path: Path) -> None:
    report_path = tmp_path / "rollback.json"
    monkeypatch.setattr(
        migration,
        "require_oss_client",
        lambda: (_ for _ in ()).throw(AssertionError("initialized OSS during rollback")),
    )
    monkeypatch.setattr(
        migration,
        "rollback_run",
        lambda factory, *, migration_id: {
            "failed": 0,
            "candidate_count": 0,
            "migration_id": migration_id,
            "factory_matches": factory is migration.SessionLocal,
            "items": {},
        },
    )

    exit_code = migration.main(
        ["--rollback-run", "run-1", "--report", str(report_path)]
    )

    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["factory_matches"] is True
