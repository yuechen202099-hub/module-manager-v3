from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.models import (  # noqa: E402
    GroupStatus,
    MaterialGroup,
    Photo,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    Team,
    TotalCatalogRow,
    UnmatchedRecord,
)
from app.services import local_simulation  # noqa: E402
from app.services.state_repository import PostgresStateRepository  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def require_database_url() -> None:
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required. Run Alembic migrations before this verifier.")


def seed_minimal_state(team_id: str) -> None:
    with SessionLocal() as session:
        session.query(Photo).filter(Photo.team_id == team_id).delete(synchronize_session=False)
        session.query(UnmatchedRecord).filter(UnmatchedRecord.team_id == team_id).delete(synchronize_session=False)
        session.query(MaterialGroup).filter(MaterialGroup.team_id == team_id).delete(synchronize_session=False)
        session.query(Task).filter(Task.team_id == team_id).delete(synchronize_session=False)
        session.query(TotalCatalogRow).filter(TotalCatalogRow.team_id == team_id).delete(synchronize_session=False)
        session.query(Project).filter(Project.team_id == team_id).delete(synchronize_session=False)
        session.query(Team).filter(Team.id == team_id).delete(synchronize_session=False)
        session.commit()

        team = Team(id=team_id, name="Postgres verifier", status="active")
        session.add(team)
        session.flush()

        project = Project(team_id=team_id, code=f"{team_id}-project", name="Postgres verifier", status=ProjectStatus.ACTIVE)
        session.add(project)
        session.flush()

        task = Task(
            team_id=team_id,
            project_id=project.id,
            legacy_id=9001,
            terminal="T-PG-001",
            title="终端 T-PG-001",
            status=TaskStatus.PUBLISHED,
        )
        session.add(task)
        session.flush()

        catalog = TotalCatalogRow(
            team_id=team_id,
            project_id=project.id,
            terminal="T-PG-001",
            original_meter_no="110099990001",
            meter_match_key="99990001",
            installation_address="上海市测试路1号",
            raw_data={},
        )
        session.add(catalog)
        session.flush()

        group = MaterialGroup(
            team_id=team_id,
            project_id=project.id,
            task_id=task.id,
            legacy_task_id=task.legacy_id,
            legacy_id="pg-group-1",
            terminal="T-PG-001",
            total_catalog_row_id=catalog.id,
            meter_match_key="99990001",
            display_meter_no="110099990001",
            installation_address="上海市测试路1号",
            status=GroupStatus.UNREVIEWED,
            photo_count=4,
            raw_data={},
        )
        exception_group = MaterialGroup(
            team_id=team_id,
            project_id=project.id,
            task_id=task.id,
            legacy_task_id=task.legacy_id,
            legacy_id="pg-group-exception",
            terminal="T-PG-001",
            meter_match_key="99990002",
            display_meter_no="110099990002",
            installation_address="上海市测试路2号",
            status=GroupStatus.INCOMPLETE,
            photo_count=2,
            has_archive_blocker=True,
            raw_data={},
        )
        session.add_all([group, exception_group])
        session.flush()

        for index, category in enumerate(["unclassified", "before_box", "module_meter", "after_box"], start=1):
            session.add(
                Photo(
                    team_id=team_id,
                    group_id=group.id,
                    legacy_id=f"pg-photo-{index}",
                    source="verifier",
                    image_url=f"https://example.test/{index}.jpg",
                    sha256=f"{index:064x}",
                    object_key=f"verifier/{index}.jpg",
                    category=category,
                    archive_status="" if category == "unclassified" else "archived",
                    sort_order=index,
                    is_active=True,
                    raw_data={},
                    metadata_json={},
                )
            )

        session.add(
            UnmatchedRecord(
                team_id=team_id,
                legacy_id="pg-unmatched-1",
                record_type="scan",
                status="open",
                terminal="T-PG-001",
                meter_no="110088880001",
                meter_match_key="88880001",
                barcode="313000000000888800010",
                collector="collector-a",
                module_asset_no="module-a",
                address="上海市未匹配路1号",
                payload={"creator": "tester", "photo_urls": ["https://example.test/unmatched.jpg"]},
            )
        )
        session.commit()


def verify_repository(team_id: str) -> None:
    token = local_simulation.set_current_team(team_id)
    try:
        repo = PostgresStateRepository()

        summary = repo.summary()["summary"]
        assert summary["groups"] == 2, summary
        assert summary["scanned_groups"] == 2, summary
        assert summary["scan_unmatched"] == 1, summary

        tasks = repo.list_tasks()
        assert len(tasks) == 1 and tasks[0]["id"] == 9001, tasks
        assert tasks[0]["can_claim"] is True, tasks[0]

        claimed = repo.claim_task(9001, "reviewer-pg")
        assert claimed["claimed_by"] == "reviewer-pg", claimed

        groups = repo.list_task_groups(9001, limit=10, summary_only=True)
        assert groups["total"] == 2, groups

        unmatched = repo.list_unmatched_records(query="8888")
        assert unmatched["total"] == 1, unmatched

        blank = repo.create_blank_unmatched_record(actor="admin-pg")
        assert blank["record"]["record_type"] == "blank_group", blank

        exception_groups = repo.list_exception_groups(reviewer="reviewer-pg")
        assert exception_groups["total"] == 1, exception_groups

        updated = repo.update_group_metadata(
            "pg-group-1",
            actor="reviewer-pg",
            updates={"collector": "collector-updated", "module_asset_no": "module-updated"},
        )
        assert updated["group"]["photos"][0]["collector"] == "collector-updated", updated

        classified = repo.classify_photo("pg-group-1", "pg-photo-1", "collector_barcode", "reviewer-pg")
        assert classified["category"] == "collector_barcode", classified

        deleted = repo.delete_photo("pg-group-1", "pg-photo-1", "reviewer-pg")
        assert deleted["deleted_photo"]["id"] == "pg-photo-1", deleted

        released = repo.release_task(9001, "reviewer-pg")
        assert released["claimed_by"] is None, released
    finally:
        local_simulation.reset_current_team(token)


def main() -> int:
    require_database_url()
    team_id = f"pg-verifier-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    seed_minimal_state(team_id)
    verify_repository(team_id)
    print(f"[OK] postgres state backend verifier passed for team {team_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
