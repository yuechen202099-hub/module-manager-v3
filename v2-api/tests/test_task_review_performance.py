from __future__ import annotations

from scripts.verify_task_review_performance import verify_measurements


def test_performance_verifier_accepts_values_at_every_threshold() -> None:
    report = verify_measurements(
        task_snapshot_ms=300,
        review_groups_ms=1500,
        review_group_count=20,
        task_builds_in_60_seconds=1,
    )

    assert report["ok"] is True
    assert report["failures"] == []


def test_performance_verifier_reports_each_exceeded_threshold() -> None:
    report = verify_measurements(
        task_snapshot_ms=301,
        review_groups_ms=1501,
        review_group_count=21,
        task_builds_in_60_seconds=2,
    )

    assert report["ok"] is False
    assert report["failures"] == [
        "task_snapshot_ms",
        "review_groups_ms",
        "review_group_count",
        "task_builds_in_60_seconds",
    ]


def test_performance_verifier_rejects_oversized_review_page() -> None:
    report = verify_measurements(
        task_snapshot_ms=120,
        review_groups_ms=300,
        review_group_count=21,
        task_builds_in_60_seconds=1,
    )

    assert report["ok"] is False
    assert "review_group_count" in report["failures"]
