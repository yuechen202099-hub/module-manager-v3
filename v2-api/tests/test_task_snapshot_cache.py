from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.services.task_snapshot_cache import TaskSnapshotCache


def snapshot(team_id: str, value: int) -> dict:
    return {"team_id": team_id, "items": [{"id": str(value)}], "version": str(value)}


def test_task_snapshot_reuses_one_build(tmp_path) -> None:
    calls = 0

    def builder(team_id: str) -> dict:
        nonlocal calls
        calls += 1
        return snapshot(team_id, calls)

    cache = TaskSnapshotCache(cache_root=tmp_path, interval_seconds=60, enabled=True)
    first = cache.get("team-a", builder)
    second = cache.get("team-a", builder)

    assert first["items"] == second["items"]
    assert calls == 1
    assert second["cache"]["type"] == "task_snapshot"


def test_stale_task_snapshot_returns_before_single_background_refresh(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def builder(team_id: str) -> dict:
        nonlocal calls
        calls += 1
        if calls > 1:
            started.set()
            release.wait(timeout=2)
        return snapshot(team_id, calls)

    cache = TaskSnapshotCache(cache_root=tmp_path, interval_seconds=30, enabled=True)
    cache.get("team-a", builder)
    cache._memory["team-a"]["generated_at"] = (
        datetime.now(UTC) - timedelta(seconds=31)
    ).isoformat()

    stale_one = cache.get("team-a", builder)
    stale_two = cache.get("team-a", builder)

    assert stale_one["cache"]["stale"] is True
    assert stale_two["items"] == stale_one["items"]
    assert started.wait(timeout=1)
    assert calls == 2
    release.set()


def test_persisted_snapshot_is_reused_after_restart(tmp_path) -> None:
    first = TaskSnapshotCache(cache_root=tmp_path, interval_seconds=60, enabled=True)
    first.refresh("team-a", lambda team_id: snapshot(team_id, 1))

    calls = 0

    def builder(team_id: str) -> dict:
        nonlocal calls
        calls += 1
        return snapshot(team_id, 2)

    loaded = TaskSnapshotCache(cache_root=tmp_path, interval_seconds=60, enabled=True)
    result = loaded.get("team-a", builder)

    assert result["version"] == "1"
    assert calls == 0
    assert result["cache"]["source"] == "file"


def test_persisted_snapshot_rejects_another_team(tmp_path) -> None:
    cache = TaskSnapshotCache(cache_root=tmp_path, interval_seconds=60, enabled=True)
    cache.refresh("team-a", lambda team_id: snapshot(team_id, 1))
    target = cache._cache_file("team-b")
    target.write_bytes(cache._cache_file("team-a").read_bytes())

    loaded = TaskSnapshotCache(cache_root=tmp_path, interval_seconds=60, enabled=True)
    result = loaded.get("team-b", lambda team_id: snapshot(team_id, 2))

    assert result["team_id"] == "team-b"
    assert result["version"] == "2"


def test_failed_refresh_keeps_previous_snapshot(tmp_path) -> None:
    cache = TaskSnapshotCache(cache_root=tmp_path, interval_seconds=60, enabled=True)
    cache.refresh("team-a", lambda team_id: snapshot(team_id, 1))

    with pytest.raises(RuntimeError, match="refresh failed"):
        cache.refresh("team-a", lambda _team_id: (_ for _ in ()).throw(RuntimeError("refresh failed")))

    result = cache.get("team-a", lambda team_id: snapshot(team_id, 2))
    assert result["version"] == "1"

