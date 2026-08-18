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
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from scripts import migrate_external_photos_to_oss as migration
from scripts.migrate_external_photos_to_oss import parse_args
from app.database import Base
from app.models import (
    AuditLog,
    DeliveryCacheJob,
    DeliveryPackageJob,
    GroupBarcodeVerification,
    GroupStatus,
    MaterialGroup,
    Photo,
    Project,
    Team,
)
from app.services.external_photo_oss_migration import DownloadedPhoto, OssObjectReceipt


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_external_photos_to_oss.py"
LEGACY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_photos_to_oss.py"


@pytest.fixture()
def external_photo_postgres():
    database_url = os.getenv("ROUND3_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("ROUND3_POSTGRES_TEST_URL is required for isolated PostgreSQL migration tests")
    parsed = make_url(database_url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"localhost", "127.0.0.1", "::1"}, "migration tests must stay on local PostgreSQL"

    schema = f"task7_{uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        execution_options={"schema_translate_map": {None: schema}},
        connect_args={
            "options": f"-csearch_path={schema},public -cstatement_timeout=15000 -clock_timeout=10000"
        },
    )
    try:
        Base.metadata.create_all(test_engine)
        yield sessionmaker(
            bind=test_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    finally:
        test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _seed_postgres_external_group(session_factory, *, photo_count: int = 2):
    team_id = f"task7-team-{uuid4().hex[:12]}"
    with session_factory.begin() as session:
        session.add(Team(id=team_id, name="Task 7 migration test"))
        session.flush()
        project = Project(team_id=team_id, code=f"TASK7-{uuid4().hex[:12]}", name="Task 7 project")
        session.add(project)
        session.flush()
        group = MaterialGroup(
            team_id=team_id,
            legacy_id=f"task7-group-{uuid4().hex[:12]}",
            project_id=project.id,
            terminal="T-TASK7",
            display_meter_no="120000000001",
            installation_address="Task 7 test road",
            status=GroupStatus.APPROVED,
            raw_data={},
        )
        session.add(group)
        session.flush()
        photo_ids = []
        for index in range(photo_count):
            url = f"https://img.example/{group.id}/{index}.jpg?token=secret"
            photo = Photo(
                team_id=team_id,
                legacy_id=f"task7-photo-{index}",
                group_id=group.id,
                image_url=url,
                source_url=url,
                storage_type="external_url",
                sha256=__import__("hashlib").sha256(url.encode("utf-8")).hexdigest(),
                original_filename=f"{index}.jpg",
                object_key=f"external/{index}.jpg",
                sort_order=index,
                is_active=True,
                raw_data={},
            )
            session.add(photo)
            session.flush()
            photo_ids.append(photo.id)
    return team_id, group.id, photo_ids


def _install_postgres_fake_io(monkeypatch, tmp_path: Path):
    temp_dir = tmp_path / f"private-run-{uuid4().hex}"
    temp_dir.mkdir(mode=0o700)
    bucket = SimpleNamespace(bucket_name="bucket-a", store_calls=[])
    monkeypatch.setattr(migration, "_new_run_temp_directory", lambda _migration_id: temp_dir)
    monkeypatch.setattr(migration, "_close_run_temp_directory", lambda _path: None)
    monkeypatch.setattr(
        migration,
        "probe_resources",
        lambda _path, **_kwargs: migration.ResourceSnapshot(
            500 * migration.MIB, 600 * migration.MIB, True, "cursor-1"
        ),
    )

    def download(source, _policy, *, temp_dir: Path):
        content = source.photo_id.encode("ascii")
        path = temp_dir / f"{source.photo_id}.jpg"
        path.write_bytes(content)
        return DownloadedPhoto(
            path,
            __import__("hashlib").sha256(content).hexdigest(),
            len(content),
            "image/jpeg",
            ".jpg",
        )

    def store(selected_bucket, bucket_name, key, photo):
        assert selected_bucket is bucket
        bucket.store_calls.append((bucket_name, key, photo.sha256))
        return OssObjectReceipt(bucket_name, key, photo.sha256, photo.byte_size, photo.content_type, False)

    monkeypatch.setattr(migration, "download_external_photo", download)
    monkeypatch.setattr(migration, "store_downloaded_photo", store)
    monkeypatch.setattr(migration, "cleanup_download", lambda photo: photo.path.unlink(missing_ok=True))
    return bucket


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


def test_dry_run_accumulates_normalized_storage_categories() -> None:
    session = _DryRunSession(
        [],
        [
            ("external_url", 2),
            (None, 1),
            ("", 2),
            ("unknown", 3),
            ("mystery", 4),
            ("oss", 5),
        ],
    )

    report = migration.run_dry_run(session, team_id="", allowlist=None)

    assert report["storage_types"] == {
        "external_url": 2,
        "mystery": 4,
        "oss": 5,
        "unknown": 6,
    }
    assert report["unknown_storage"] == 10


def test_start_gate_requires_memory_disk_health_and_no_new_oom() -> None:
    with pytest.raises(migration.ResourceGateError, match="400 MiB"):
        migration.start_gate(migration.ResourceSnapshot(399 * migration.MIB, 600 * migration.MIB, True, "cursor-1"))
    with pytest.raises(migration.ResourceGateError, match="512 MiB"):
        migration.start_gate(migration.ResourceSnapshot(500 * migration.MIB, 511 * migration.MIB, True, "cursor-1"))
    with pytest.raises(migration.ResourceGateError, match="health"):
        migration.start_gate(migration.ResourceSnapshot(500 * migration.MIB, 600 * migration.MIB, False, "cursor-1"))


def test_start_gate_fails_closed_when_journal_monitor_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(migration, "_memory_available_bytes", lambda: 500 * migration.MIB)
    monkeypatch.setattr(migration, "_api_is_healthy", lambda: True)
    monkeypatch.setattr(
        migration.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=b"", stderr=b"permission denied"),
    )

    snapshot = migration.probe_resources(tmp_path)

    with pytest.raises(migration.ResourceGateError, match="OOM monitor"):
        migration.start_gate(snapshot)


def test_oom_monitor_uses_an_advancing_journal_cursor(monkeypatch) -> None:
    commands: list[list[str]] = []
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout=b"-- cursor: cursor-1\n", stderr=b""),
            SimpleNamespace(
                returncode=0,
                stdout=b"kernel: oom-kill:constraint=CONSTRAINT_NONE\n-- cursor: cursor-2\n",
                stderr=b"",
            ),
        ]
    )

    def journalctl(command, **_kwargs):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(migration.subprocess, "run", journalctl)

    initial = migration._oom_marker()

    assert getattr(initial, "valid", None) is True
    assert initial.cursor == "cursor-1"
    assert initial.oom_detected is False

    advanced = migration._oom_marker(initial.cursor)

    assert advanced.valid is True
    assert advanced.cursor == "cursor-2"
    assert advanced.oom_detected is True
    assert "--show-cursor" in commands[0]
    assert commands[0][commands[0].index("-n") + 1] == "0"
    assert commands[1][commands[1].index("--after-cursor") + 1] == "cursor-1"


def test_transfer_resource_probes_advance_from_the_latest_cursor(monkeypatch, tmp_path: Path) -> None:
    candidate = _candidate()
    _install_safe_run_boundaries(monkeypatch, tmp_path, [candidate])
    cursors: list[str] = []
    probes = iter(
        [
            migration.ResourceSnapshot(500 * migration.MIB, 600 * migration.MIB, True, "cursor-1"),
            migration.ResourceSnapshot(249 * migration.MIB, 600 * migration.MIB, True, "cursor-2"),
        ]
    )

    def probe(_path: Path, *, oom_cursor: str = ""):
        cursors.append(oom_cursor)
        return next(probes)

    monkeypatch.setattr(migration, "probe_resources", probe)

    migration.execute_run(
        lambda: None,
        SimpleNamespace(bucket_name="bucket-a"),
        migration_id="run-1",
        allowlist=frozenset({"img.example"}),
    )

    assert cursors == ["", "cursor-1"]


@pytest.mark.parametrize(
    ("snapshot", "errors", "reason"),
    [
        ((249, 600, True, "cursor-1", True, False), 0, "low_memory"),
        ((500, 600, False, "cursor-1", True, False), 0, "health_failed"),
        ((500, 600, True, "cursor-2", True, True), 0, "new_oom"),
        ((500, 600, True, "cursor-1", True, False), 5, "oss_error_limit"),
        ((500, 600, True, "cursor-1", False, False), 0, "oom_monitor_failed"),
    ],
)
def test_runtime_stop_reasons(snapshot: tuple[int, int, bool, str, bool, bool], errors: int, reason: str) -> None:
    mem_mib, disk_mib, healthy, marker, monitor_valid, oom_detected = snapshot
    resource = migration.ResourceSnapshot(
        mem_mib * migration.MIB,
        disk_mib * migration.MIB,
        healthy,
        marker,
        monitor_valid,
        oom_detected,
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


def test_explicit_report_preserves_preexisting_parent_permissions(monkeypatch, tmp_path: Path) -> None:
    report_parent = tmp_path / "operator-owned"
    report_parent.mkdir()
    report_parent.chmod(0o750)
    original_mode = stat.S_IMODE(report_parent.stat().st_mode)
    real_chmod = Path.chmod

    def reject_parent_chmod(path: Path, mode: int, *args, **kwargs) -> None:
        if path == report_parent:
            raise AssertionError("explicit report parent permissions were changed")
        real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", reject_parent_chmod)

    path = migration.write_report(report_parent / "run.json", {"status": "ok"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "ok"}
    assert stat.S_IMODE(report_parent.stat().st_mode) == original_mode
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_report_redacts_sensitive_keys_and_secret_patterns(tmp_path: Path) -> None:
    path = migration.write_report(
        tmp_path / "run.json",
        {
            "access_token": "top-secret-token",
            "nested": {
                "password": "hunter2",
                "note": (
                    "Authorization: Bearer bearer-secret; "
                    "AccessKeyId=LTAI1234567890SECRET; Signature=signature-secret"
                ),
                "safe": "visible",
            },
        },
    )

    content = path.read_text(encoding="utf-8")
    payload = json.loads(content)

    assert "top-secret-token" not in content
    assert "hunter2" not in content
    assert "bearer-secret" not in content
    assert "LTAI1234567890SECRET" not in content
    assert "signature-secret" not in content
    assert payload["access_token"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    assert payload["nested"]["safe"] == "visible"


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
        lambda _path, **_kwargs: migration.ResourceSnapshot(
            500 * migration.MIB, 600 * migration.MIB, True, "cursor-1"
        ),
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


def test_oss_errors_use_allowlisted_report_details(monkeypatch, tmp_path: Path) -> None:
    candidate = _candidate()
    _install_safe_run_boundaries(monkeypatch, tmp_path, [candidate])

    def download(*_args, temp_dir: Path, **_kwargs):
        path = temp_dir / "download.jpg"
        path.write_bytes(b"image")
        return DownloadedPhoto(path, "a" * 64, 5, "image/jpeg", ".jpg")

    monkeypatch.setattr(migration, "download_external_photo", download)
    monkeypatch.setattr(
        migration,
        "store_downloaded_photo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            migration.OssVerificationError(
                "AccessKeyId=LTAI1234567890SECRET Signature=signature-secret token=top-secret-token"
            )
        ),
    )

    report = migration.execute_run(
        lambda: None,
        SimpleNamespace(bucket_name="bucket-a"),
        migration_id="run-1",
        allowlist=frozenset({"img.example"}),
    )
    item = report["items"][str(candidate.photo_id)]

    assert item["status"] == "oss_verification_failed"
    assert item["error_category"] == "oss"
    assert item["error_code"] == "verification_failed"
    assert item["error"] == "OSS object verification failed"
    assert "LTAI1234567890SECRET" not in json.dumps(report)
    assert "signature-secret" not in json.dumps(report)
    assert "top-secret-token" not in json.dumps(report)


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
        self.query_statements = []

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

    def execute(self, statement):
        assert self.in_transaction
        self.query_statements.append(statement)
        return _Rows([(photo.id, photo.sha256) for photo in self.photos])

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
    monkeypatch.setattr(migration, "_final_delivery_ready", lambda *_args: False)

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
    photo_lock_sql = next(str(statement) for statement in session.lock_statements if "FROM photos" in str(statement))
    assert "photos.id IN" in photo_lock_sql
    duplicate_sql = str(session.query_statements[0])
    assert "photos.group_id =" in duplicate_sql
    assert "lower(photos.sha256) IN" in duplicate_sql
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


def test_commit_uses_authoritative_post_mutation_delivery_readiness(monkeypatch) -> None:
    candidate = _candidate()
    group = SimpleNamespace(id=candidate.group_id, team_id="team-a", legacy_id="group-1", status="approved")
    photo = _photo_for(candidate)
    session = _CommitSession(group, [photo])
    monkeypatch.setattr(migration, "invalidate_verification_for_group", lambda *_args, **_kwargs: {})

    def group_payload(current, locked_group, *, include_photos: bool):
        assert current is session
        assert locked_group is group
        assert include_photos is True
        assert photo.storage_type == "oss"
        return {"status": "approved", "photos": []}

    monkeypatch.setattr(migration, "_group_payload", group_payload, raising=False)

    result = migration._commit_group(
        lambda: session,
        group_id=candidate.group_id,
        transfers=[_transfer_for(candidate)],
        migration_id="run-1",
    )

    assert result["statuses"][str(candidate.photo_id)] == "committed"
    assert result["final_delivery_ready"] is False


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


def test_duplicate_content_lookup_normalizes_stored_digest_case(monkeypatch) -> None:
    candidate = _candidate()
    transfer_sha = "abcdef" * 10 + "abcd"
    group = SimpleNamespace(id=candidate.group_id, team_id="team-a", legacy_id="group-1", status="approved")
    target = _photo_for(candidate)
    existing = SimpleNamespace(id=uuid4(), sha256=transfer_sha.upper())
    session = _CommitSession(group, [target, existing])
    monkeypatch.setattr(
        migration,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalidated duplicate")),
    )

    result = migration._commit_group(
        lambda: session,
        group_id=candidate.group_id,
        transfers=[_transfer_for(candidate, sha256=transfer_sha)],
        migration_id="run-1",
    )

    duplicate_sql = str(session.query_statements[0].compile(dialect=postgresql.dialect()))
    assert "photos.group_id =" in duplicate_sql
    assert "lower(photos.sha256) IN" in duplicate_sql
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
    monkeypatch.setattr(migration, "probe_resources", lambda _path, **_kwargs: next(probes))
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
    monkeypatch.setattr(migration, "_final_delivery_ready", lambda *_args: False)

    report = migration.rollback_run(lambda: session, migration_id="run-1")

    assert report["rolled_back"] == 1
    assert photo.storage_type == "external_url"
    assert photo.image_url == "https://img.example/photo.jpg?token=secret"
    assert "oss_rollback_at" in photo.raw_data
    assert invalidations == ["invalidated"]


def test_rollback_discovery_includes_changed_storage_and_excludes_completed_rows() -> None:
    class CaptureSession:
        def __init__(self) -> None:
            self.statement = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            if not str(statement).startswith("SET TRANSACTION"):
                self.statement = statement
            return _Rows([])

        def rollback(self) -> None:
            pass

    session = CaptureSession()

    candidates = migration._fetch_rollback_candidates(lambda: session, migration_id="run-1")

    assert candidates == []
    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "photos.storage_type" not in sql
    assert "oss_migration_id" in sql
    assert "oss_rollback_at" in sql
    assert "IS NULL" in sql


def test_postgres_execute_locks_transferred_rows_persists_jsonb_and_invalidates_once(
    external_photo_postgres,
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_factory = external_photo_postgres
    team_id, group_id, photo_ids = _seed_postgres_external_group(session_factory)
    bucket = _install_postgres_fake_io(monkeypatch, tmp_path)
    statements: list[str] = []
    engine = session_factory.kw["bind"]

    def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_sql)
    try:
        report = migration.execute_run(
            session_factory,
            bucket,
            migration_id="pg-run-1",
            allowlist=frozenset({"img.example"}),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)

    assert report["committed"] == 2
    assert report["failed"] == 0
    assert len(bucket.store_calls) == 2
    assert any("FROM " in sql and "photos" in sql and "id IN" in sql and "FOR UPDATE" in sql for sql in statements)
    with session_factory() as session:
        photos = list(session.scalars(select(Photo).where(Photo.id.in_(photo_ids)).order_by(Photo.id)).all())
        assert all(photo.storage_type == "oss" for photo in photos)
        assert all(photo.raw_data["oss_migration_id"] == "pg-run-1" for photo in photos)
        assert all(photo.raw_data["pre_oss_storage_type"] == "external_url" for photo in photos)
        assert session.scalar(
            select(func.count(GroupBarcodeVerification.id)).where(
                GroupBarcodeVerification.team_id == team_id,
                GroupBarcodeVerification.group_id == group_id,
            )
        ) == 1
        assert session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.team_id == team_id,
                AuditLog.action == "group_barcode_verification_invalidated",
            )
        ) == 1
        assert session.scalar(select(func.count(DeliveryCacheJob.id))) == 0
        assert session.scalar(select(func.count(DeliveryPackageJob.id))) == 0


def test_postgres_uppercase_digest_is_detected_as_duplicate_content(
    external_photo_postgres,
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_factory = external_photo_postgres
    team_id, _group_id, photo_ids = _seed_postgres_external_group(session_factory)
    target_id, blocker_id = photo_ids
    target_digest = __import__("hashlib").sha256(str(target_id).encode("ascii")).hexdigest()
    assert target_digest != target_digest.upper()
    with session_factory.begin() as session:
        blocker = session.get(Photo, blocker_id)
        blocker.storage_type = "local_upload"
        blocker.sha256 = target_digest.upper()
    bucket = _install_postgres_fake_io(monkeypatch, tmp_path)

    report = migration.execute_run(
        session_factory,
        bucket,
        migration_id="pg-case-duplicate",
        allowlist=frozenset({"img.example"}),
    )

    assert report["committed"] == 0
    assert report["failure_counts"] == {"duplicate_content": 1}
    with session_factory() as session:
        target = session.get(Photo, target_id)
        blocker = session.get(Photo, blocker_id)
        assert target.storage_type == "external_url"
        assert "oss_migration_id" not in target.raw_data
        assert blocker.sha256 == target_digest.upper()
        assert session.scalar(select(func.count(GroupBarcodeVerification.id))) == 0
        assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.team_id == team_id)) == 0


def test_postgres_unique_constraint_rolls_back_the_group_commit(
    external_photo_postgres,
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_factory = external_photo_postgres
    team_id, _group_id, photo_ids = _seed_postgres_external_group(session_factory)
    target_id, blocker_id = photo_ids
    target_digest = __import__("hashlib").sha256(str(target_id).encode("ascii")).hexdigest()
    with session_factory.begin() as session:
        blocker = session.get(Photo, blocker_id)
        blocker.storage_type = "local_upload"
        blocker.sha256 = "b" * 64
    bucket = _install_postgres_fake_io(monkeypatch, tmp_path)
    engine = session_factory.kw["bind"]
    raced = False

    def create_duplicate_after_digest_query(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal raced
        if (
            raced
            or "SELECT" not in statement
            or "photos" not in statement
            or "lower(" not in statement
            or "sha256" not in statement
            or " IN " not in statement
        ):
            return
        raced = True
        with session_factory.begin() as other_session:
            other_session.get(Photo, blocker_id).sha256 = target_digest

    event.listen(engine, "after_cursor_execute", create_duplicate_after_digest_query)
    try:
        report = migration.execute_run(
            session_factory,
            bucket,
            migration_id="pg-constraint",
            allowlist=frozenset({"img.example"}),
        )
    finally:
        event.remove(engine, "after_cursor_execute", create_duplicate_after_digest_query)

    assert raced is True
    assert report["committed"] == 0
    assert report["failure_counts"] == {"commit_failed": 1}
    with session_factory() as session:
        target = session.get(Photo, target_id)
        blocker = session.get(Photo, blocker_id)
        assert target.storage_type == "external_url"
        assert "oss_migration_id" not in target.raw_data
        assert blocker.sha256 == target_digest
        assert session.scalar(select(func.count(GroupBarcodeVerification.id))) == 0
        assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.team_id == team_id)) == 0
        assert session.scalar(select(func.count(DeliveryCacheJob.id))) == 0
        assert session.scalar(select(func.count(DeliveryPackageJob.id))) == 0


def test_postgres_concurrent_source_change_is_a_locked_conflict(
    external_photo_postgres,
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_factory = external_photo_postgres
    team_id, _group_id, photo_ids = _seed_postgres_external_group(session_factory, photo_count=1)
    photo_id = photo_ids[0]
    bucket = _install_postgres_fake_io(monkeypatch, tmp_path)
    changed_url = "https://new.example/concurrent.jpg"

    def store(_bucket, bucket_name, key, photo):
        with session_factory.begin() as concurrent_session:
            concurrent_session.get(Photo, photo_id).image_url = changed_url
        return OssObjectReceipt(bucket_name, key, photo.sha256, photo.byte_size, photo.content_type, False)

    monkeypatch.setattr(migration, "store_downloaded_photo", store)

    report = migration.execute_run(
        session_factory,
        bucket,
        migration_id="pg-conflict",
        allowlist=frozenset({"img.example"}),
    )

    assert report["committed"] == 0
    assert report["conflicts"] == 1
    with session_factory() as session:
        photo = session.get(Photo, photo_id)
        assert photo.image_url == changed_url
        assert photo.storage_type == "external_url"
        assert "oss_migration_id" not in photo.raw_data
        assert session.scalar(select(func.count(GroupBarcodeVerification.id))) == 0
        assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.team_id == team_id)) == 0


def test_postgres_rollback_discovers_changed_storage_and_reports_conflict(
    external_photo_postgres,
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_factory = external_photo_postgres
    team_id, _group_id, photo_ids = _seed_postgres_external_group(session_factory)
    bucket = _install_postgres_fake_io(monkeypatch, tmp_path)
    executed = migration.execute_run(
        session_factory,
        bucket,
        migration_id="pg-rollback-conflict",
        allowlist=frozenset({"img.example"}),
    )
    assert executed["committed"] == 2
    changed_id, exact_id = photo_ids
    with session_factory.begin() as session:
        changed = session.get(Photo, changed_id)
        changed.storage_type = "local_upload"
        changed.image_url = "local://concurrent-change"

    report = migration.rollback_run(session_factory, migration_id="pg-rollback-conflict")

    assert report["candidate_count"] == 2
    assert report["rolled_back"] == 1
    assert report["conflicts"] == 1
    with session_factory() as session:
        changed = session.get(Photo, changed_id)
        exact = session.get(Photo, exact_id)
        assert changed.storage_type == "local_upload"
        assert changed.image_url == "local://concurrent-change"
        assert "oss_rollback_at" not in changed.raw_data
        assert exact.storage_type == "external_url"
        assert "oss_rollback_at" in exact.raw_data
        assert session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.team_id == team_id,
                AuditLog.action == "group_barcode_verification_invalidated",
            )
        ) == 2
        assert session.scalar(select(func.count(DeliveryCacheJob.id))) == 0
        assert session.scalar(select(func.count(DeliveryPackageJob.id))) == 0


def test_postgres_same_migration_id_can_rollback_after_recommit(
    external_photo_postgres,
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_factory = external_photo_postgres
    _team_id, _group_id, photo_ids = _seed_postgres_external_group(session_factory, photo_count=1)
    photo_id = photo_ids[0]
    bucket = _install_postgres_fake_io(monkeypatch, tmp_path)
    migration_id = "pg-repeat-cycle"

    first_execute = migration.execute_run(
        session_factory,
        bucket,
        migration_id=migration_id,
        allowlist=frozenset({"img.example"}),
    )
    assert first_execute["committed"] == 1

    first_rollback = migration.rollback_run(session_factory, migration_id=migration_id)
    assert first_rollback["candidate_count"] == 1
    assert first_rollback["rolled_back"] == 1
    assert migration._fetch_rollback_candidates(session_factory, migration_id=migration_id) == []

    recommit = migration.execute_run(
        session_factory,
        bucket,
        migration_id=migration_id,
        allowlist=frozenset({"img.example"}),
    )
    assert recommit["committed"] == 1

    second_rollback = migration.rollback_run(session_factory, migration_id=migration_id)
    assert second_rollback["candidate_count"] == 1
    assert second_rollback["rolled_back"] == 1
    with session_factory() as session:
        photo = session.get(Photo, photo_id)
        assert photo.storage_type == "external_url"
        assert photo.image_url.startswith("https://img.example/")
        assert "oss_rollback_at" in photo.raw_data


def test_postgres_rollback_invalidation_failure_is_atomic(
    external_photo_postgres,
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_factory = external_photo_postgres
    team_id, group_id, photo_ids = _seed_postgres_external_group(session_factory)
    bucket = _install_postgres_fake_io(monkeypatch, tmp_path)
    executed = migration.execute_run(
        session_factory,
        bucket,
        migration_id="pg-rollback-atomic",
        allowlist=frozenset({"img.example"}),
    )
    assert executed["committed"] == 2
    with session_factory() as session:
        before_version = session.scalar(
            select(GroupBarcodeVerification.evidence_version).where(
                GroupBarcodeVerification.team_id == team_id,
                GroupBarcodeVerification.group_id == group_id,
            )
        )
        before_audits = session.scalar(select(func.count(AuditLog.id)).where(AuditLog.team_id == team_id))
    real_invalidate = migration.invalidate_verification_for_group

    def fail_after_invalidation(*args, **kwargs):
        real_invalidate(*args, **kwargs)
        raise RuntimeError("forced rollback invalidation failure")

    monkeypatch.setattr(migration, "invalidate_verification_for_group", fail_after_invalidation)

    report = migration.rollback_run(session_factory, migration_id="pg-rollback-atomic")

    assert report["rolled_back"] == 0
    assert report["failure_counts"] == {"rollback_failed": 2}
    with session_factory() as session:
        photos = list(session.scalars(select(Photo).where(Photo.id.in_(photo_ids))).all())
        assert all(photo.storage_type == "oss" for photo in photos)
        assert all("oss_rollback_at" not in photo.raw_data for photo in photos)
        assert session.scalar(
            select(GroupBarcodeVerification.evidence_version).where(
                GroupBarcodeVerification.team_id == team_id,
                GroupBarcodeVerification.group_id == group_id,
            )
        ) == before_version
        assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.team_id == team_id)) == before_audits
        assert session.scalar(select(func.count(DeliveryCacheJob.id))) == 0
        assert session.scalar(select(func.count(DeliveryPackageJob.id))) == 0


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
