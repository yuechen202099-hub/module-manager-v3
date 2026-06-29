from __future__ import annotations

import threading
import time

from app.services.project_board_cache import ProjectBoardSummaryCache


def test_project_board_summary_cache_reuses_memory_snapshot(tmp_path) -> None:
    calls = 0
    cache = ProjectBoardSummaryCache(cache_root=tmp_path, interval_seconds=300, enabled=True)

    def build_summary() -> dict:
        nonlocal calls
        calls += 1
        return {"summary": {"team_id": "team-a", "groups": calls}, "paths": {}}

    first = cache.get("team-a", build_summary)
    second = cache.get("team-a", build_summary)

    assert calls == 1
    assert first["summary"]["groups"] == 1
    assert second["summary"]["groups"] == 1
    assert second["cache"]["type"] == "project_board_summary"
    assert second["cache"]["source"] in {"cold", "memory"}


def test_project_board_summary_cache_loads_file_snapshot_after_restart(tmp_path) -> None:
    cache = ProjectBoardSummaryCache(cache_root=tmp_path, interval_seconds=300, enabled=True)
    cache.get("team-a", lambda: {"summary": {"team_id": "team-a", "groups": 7}, "paths": {}})

    restarted_cache = ProjectBoardSummaryCache(cache_root=tmp_path, interval_seconds=300, enabled=True)
    snapshot = restarted_cache.get(
        "team-a",
        lambda: (_ for _ in ()).throw(AssertionError("should read the cached file instead of recomputing")),
    )

    assert snapshot["summary"]["groups"] == 7
    assert snapshot["cache"]["source"] == "file"


def test_project_board_summary_cache_discards_mismatched_team_snapshot(tmp_path) -> None:
    cache = ProjectBoardSummaryCache(cache_root=tmp_path, interval_seconds=300, enabled=True)
    cache.get("team-a", lambda: {"summary": {"team_id": "default-team", "groups": 7}, "paths": {}})

    calls = 0

    def build_summary() -> dict:
        nonlocal calls
        calls += 1
        return {"summary": {"team_id": "team-a", "groups": 9}, "paths": {}}

    snapshot = cache.get("team-a", build_summary)

    assert calls == 1
    assert snapshot["summary"]["team_id"] == "team-a"
    assert snapshot["summary"]["groups"] == 9
    assert snapshot["cache"]["source"] == "cold"


def test_project_board_summary_cache_force_refresh_recomputes(tmp_path) -> None:
    calls = 0
    cache = ProjectBoardSummaryCache(cache_root=tmp_path, interval_seconds=300, enabled=True)

    def build_summary() -> dict:
        nonlocal calls
        calls += 1
        return {"summary": {"team_id": "team-a", "groups": calls}, "paths": {}}

    cache.get("team-a", build_summary)
    refreshed = cache.get("team-a", build_summary, force_refresh=True)

    assert calls == 2
    assert refreshed["summary"]["groups"] == 2
    assert refreshed["cache"]["source"] == "refresh"


def test_project_board_summary_cache_waits_for_cold_refresh_in_progress(tmp_path) -> None:
    calls = 0
    cache = ProjectBoardSummaryCache(cache_root=tmp_path, interval_seconds=300, enabled=True)
    builder_started = threading.Event()
    release_builder = threading.Event()
    results: list[dict] = []

    def build_summary() -> dict:
        nonlocal calls
        calls += 1
        builder_started.set()
        release_builder.wait(timeout=5)
        return {"summary": {"team_id": "team-a", "groups": calls}, "paths": {}}

    first = threading.Thread(target=lambda: results.append(cache.get("team-a", build_summary)))
    second = threading.Thread(target=lambda: results.append(cache.get("team-a", build_summary)))

    first.start()
    assert builder_started.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    release_builder.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert calls == 1
    assert len(results) == 2
    assert {item["summary"]["groups"] for item in results} == {1}
