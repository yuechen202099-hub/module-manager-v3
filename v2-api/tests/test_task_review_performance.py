from __future__ import annotations

import pytest

from scripts import verify_task_review_performance as performance_verifier

verify_measurements = performance_verifier.verify_measurements


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


def test_observed_build_count_uses_monotonic_cache_counters() -> None:
    assert performance_verifier.observed_build_count(4, 5, "instance-a", "instance-a") == 1
    assert performance_verifier.observed_build_count(5, 5, "instance-a", "instance-a") == 0
    with pytest.raises(ValueError, match="counter moved backwards"):
        performance_verifier.observed_build_count(5, 3, "instance-a", "instance-a")
    with pytest.raises(ValueError, match="cache restarted"):
        performance_verifier.observed_build_count(5, 6, "instance-a", "instance-b")
