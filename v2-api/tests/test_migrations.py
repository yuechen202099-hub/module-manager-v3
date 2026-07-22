from __future__ import annotations

from pathlib import Path


def test_group_barcode_verification_migration_creates_constraints_indexes_and_downgrade() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (root / "alembic" / "versions" / "0006_group_barcode_verification.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "20260722_0006"' in migration
    assert 'down_revision = "20260721_0005"' in migration
    assert 'op.create_table(\n        "group_barcode_verifications"' in migration
    assert 'op.create_table(\n        "barcode_maintenance_controls"' in migration
    assert 'sa.UniqueConstraint("team_id", "group_id", name="uq_group_barcode_verifications_team_group")' in migration
    assert '"ix_group_barcode_verifications_pending"' in migration
    assert '"ix_group_barcode_verifications_lease"' in migration
    assert 'op.drop_table("group_barcode_verifications")' in migration
    assert 'op.drop_table("barcode_maintenance_controls")' in migration
