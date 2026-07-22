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


def test_run_verification_records_real_route_and_nonempty_response_evidence(monkeypatch) -> None:
    snapshots = [
        (
            {
                "version": "snapshot-v1",
                "items": [{"id": 1}],
                "cache": {"build_count": 4, "instance_id": "cache-a", "generated_at": "first"},
            },
            80.0,
        ),
        (
            {
                "version": "snapshot-v1",
                "items": [{"id": 1}],
                "cache": {"build_count": 4, "instance_id": "cache-a", "generated_at": "first"},
            },
            25.0,
        ),
        (
            {"items": [{"id": "group-1"}], "total": 1, "limit": 20, "offset": 0},
            40.0,
        ),
        (
            {
                "version": "snapshot-v1",
                "items": [{"id": 1}],
                "cache": {"build_count": 5, "instance_id": "cache-a", "generated_at": "first"},
            },
            20.0,
        ),
    ]
    paths: list[str] = []

    def fake_timed_get(_base_url: str, path: str, _token: str):
        paths.append(path)
        return snapshots.pop(0)

    sleeps: list[float] = []
    monkeypatch.setattr(performance_verifier, "timed_get", fake_timed_get)

    report = performance_verifier.run_verification(
        "http://127.0.0.1:18010",
        "token",
        source_commit="a" * 40,
        sleeper=sleeps.append,
        sample_seconds=60,
    )

    assert report["ok"] is True
    assert report["source_commit"] == "a" * 40
    assert report["task_id"] == "1"
    assert report["build_sample_seconds"] == 60
    assert report["start_cache_instance_id"] == report["end_cache_instance_id"] == "cache-a"
    assert report["routes"]["task_snapshot"] == {
        "path": "/local-test/tasks/snapshot",
        "item_count": 1,
        "selected_task_id": "1",
        "serialized_bytes": report["routes"]["task_snapshot"]["serialized_bytes"],
    }
    assert report["routes"]["task_snapshot"]["serialized_bytes"] > 0
    assert report["routes"]["review_groups"]["item_count"] == 1
    assert report["routes"]["review_groups"]["total"] == 1
    assert report["routes"]["review_groups"]["limit"] == 20
    assert report["routes"]["review_groups"]["offset"] == 0
    assert report["routes"]["review_groups"]["serialized_bytes"] > 0
    assert paths == [
        "/local-test/tasks/snapshot",
        "/local-test/tasks/snapshot",
        "/local-test/tasks/1/review-groups?limit=20&offset=0&review_status=all&query=",
        "/local-test/tasks/snapshot",
    ]
    assert sleeps == [60]
