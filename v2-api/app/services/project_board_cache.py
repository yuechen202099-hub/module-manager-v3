from __future__ import annotations

import json
import logging
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings

SummaryBuilder = Callable[[], dict[str, Any]]
logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_team_id(team_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", team_id.strip())
    return safe.strip(".-") or "default-team"


def default_project_board_cache_root() -> Path:
    configured = getattr(settings, "project_board_summary_cache_path", "").strip()
    if configured:
        return Path(configured)
    auth_users_path = getattr(settings, "auth_users_path", "").strip()
    if auth_users_path:
        return Path(auth_users_path).resolve().parent / "project-board-cache"
    return Path.cwd().resolve() / "data" / "project-board-cache"


class ProjectBoardSummaryCache:
    def __init__(
        self,
        *,
        cache_root: Path | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        configured_interval = int(
            interval_seconds
            if interval_seconds is not None
            else getattr(settings, "project_board_summary_cache_seconds", 300)
        )
        self.interval_seconds = max(30, configured_interval)
        self.enabled = bool(
            enabled if enabled is not None else getattr(settings, "project_board_summary_cache_enabled", True)
        )
        self.cache_root = cache_root or default_project_board_cache_root()
        self._lock = threading.RLock()
        self._memory: dict[str, dict[str, Any]] = {}
        self._refreshing: set[str] = set()
        self._refresh_events: dict[str, threading.Event] = {}
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None

    def get(self, team_id: str, builder: SummaryBuilder, *, force_refresh: bool = False) -> dict[str, Any]:
        if not self.enabled:
            return builder()
        safe_team_id = _safe_team_id(team_id)
        if force_refresh:
            return self.refresh(safe_team_id, builder, source="refresh")

        snapshot = self._snapshot_for_team(safe_team_id)
        if snapshot is None:
            return self.refresh(safe_team_id, builder, source="cold")

        stale = self._is_stale(snapshot)
        if stale:
            self.refresh_async(safe_team_id, builder)
        return self._payload_with_cache_meta(snapshot, stale=stale, source=snapshot.get("source") or "memory")

    def refresh(self, team_id: str, builder: SummaryBuilder, *, source: str = "refresh") -> dict[str, Any]:
        safe_team_id = _safe_team_id(team_id)
        owner_event: threading.Event | None = None
        wait_event: threading.Event | None = None
        with self._lock:
            if safe_team_id in self._refreshing:
                snapshot = self._memory.get(safe_team_id) or self._load_from_file(safe_team_id)
                if snapshot is not None:
                    return self._payload_with_cache_meta(snapshot, stale=True, source=snapshot.get("source") or "memory")
                wait_event = self._refresh_events.get(safe_team_id)
            else:
                owner_event = threading.Event()
                self._refresh_events[safe_team_id] = owner_event
                self._refreshing.add(safe_team_id)

        if wait_event is not None:
            wait_event.wait()
            snapshot = self._snapshot_for_team(safe_team_id)
            if snapshot is not None:
                return self._payload_with_cache_meta(
                    snapshot,
                    stale=self._is_stale(snapshot),
                    source=snapshot.get("source") or "memory",
                )
            with self._lock:
                owner_event = threading.Event()
                self._refresh_events[safe_team_id] = owner_event
                self._refreshing.add(safe_team_id)

        if owner_event is None:
            owner_event = threading.Event()
            with self._lock:
                self._refresh_events[safe_team_id] = owner_event
                self._refreshing.add(safe_team_id)

        try:
            payload = builder()
            snapshot = {
                "generated_at": _utc_now().isoformat(),
                "payload": deepcopy(payload),
                "source": source,
            }
            self._store_snapshot(safe_team_id, snapshot)
            return self._payload_with_cache_meta(snapshot, stale=False, source=source)
        finally:
            with self._lock:
                self._refreshing.discard(safe_team_id)
                if self._refresh_events.get(safe_team_id) is owner_event:
                    self._refresh_events.pop(safe_team_id, None)
            owner_event.set()

    def refresh_async(self, team_id: str, builder: SummaryBuilder) -> None:
        safe_team_id = _safe_team_id(team_id)
        with self._lock:
            if safe_team_id in self._refreshing:
                return
            self._refreshing.add(safe_team_id)

        def runner() -> None:
            try:
                payload = builder()
                snapshot = {
                    "generated_at": _utc_now().isoformat(),
                    "payload": deepcopy(payload),
                    "source": "background",
                }
                self._store_snapshot(safe_team_id, snapshot)
            except Exception:
                logger.exception("Project board summary background refresh failed for team %s", safe_team_id)
            finally:
                with self._lock:
                    self._refreshing.discard(safe_team_id)
                    event = self._refresh_events.pop(safe_team_id, None)
                    if event is not None:
                        event.set()

        threading.Thread(target=runner, name=f"project-board-summary-cache-{safe_team_id}", daemon=True).start()

    def start(self, team_id_provider: Callable[[], str], builder: SummaryBuilder) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop_event.clear()

        def loop() -> None:
            while not self._stop_event.is_set():
                try:
                    self.refresh(team_id_provider(), builder, source="scheduled")
                except Exception:
                    logger.exception("Project board summary scheduled refresh failed")
                self._stop_event.wait(self.interval_seconds)

        self._worker = threading.Thread(target=loop, name="project-board-summary-cache", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=2)

    def _snapshot_for_team(self, safe_team_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._memory.get(safe_team_id)
        if snapshot is not None:
            if not self._snapshot_matches_team(snapshot, safe_team_id):
                self._discard_snapshot(safe_team_id)
                return None
            return snapshot
        snapshot = self._load_from_file(safe_team_id)
        if snapshot is not None:
            if not self._snapshot_matches_team(snapshot, safe_team_id):
                self._discard_snapshot(safe_team_id)
                return None
            with self._lock:
                self._memory[safe_team_id] = snapshot
        return snapshot

    def _cache_file(self, safe_team_id: str) -> Path:
        return self.cache_root / f"summary-{safe_team_id}.json"

    def _load_from_file(self, safe_team_id: str) -> dict[str, Any] | None:
        path = self._cache_file(safe_team_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
            return None
        data["source"] = "file"
        return data

    def _snapshot_matches_team(self, snapshot: dict[str, Any], safe_team_id: str) -> bool:
        payload = snapshot.get("payload") if isinstance(snapshot, dict) else {}
        summary = payload.get("summary") if isinstance(payload, dict) else {}
        snapshot_team_id = _safe_team_id(str((summary or {}).get("team_id") or ""))
        return snapshot_team_id == safe_team_id

    def _discard_snapshot(self, safe_team_id: str) -> None:
        with self._lock:
            self._memory.pop(safe_team_id, None)
        try:
            self._cache_file(safe_team_id).unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to discard mismatched project board summary cache for team %s", safe_team_id)

    def _store_snapshot(self, safe_team_id: str, snapshot: dict[str, Any]) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        path = self._cache_file(safe_team_id)
        tmp_path = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp_path.replace(path)
        with self._lock:
            self._memory[safe_team_id] = snapshot

    def _is_stale(self, snapshot: dict[str, Any]) -> bool:
        generated_at = _parse_iso_datetime(str(snapshot.get("generated_at") or ""))
        if generated_at is None:
            return True
        age_seconds = (_utc_now() - generated_at).total_seconds()
        return age_seconds >= self.interval_seconds

    def _payload_with_cache_meta(self, snapshot: dict[str, Any], *, stale: bool, source: str) -> dict[str, Any]:
        payload = deepcopy(snapshot.get("payload") or {})
        payload["cache"] = {
            "type": "project_board_summary",
            "source": source,
            "generated_at": snapshot.get("generated_at") or "",
            "stale": stale,
            "refresh_interval_seconds": self.interval_seconds,
        }
        return payload


project_board_summary_cache = ProjectBoardSummaryCache()


def _default_team_id() -> str:
    from app.services.local_simulation import current_team_id

    return current_team_id()


def _default_summary_builder() -> dict[str, Any]:
    from app.services.state_repository import get_state_repository

    return get_state_repository().summary()


def start_project_board_summary_cache() -> None:
    project_board_summary_cache.start(_default_team_id, _default_summary_builder)


def stop_project_board_summary_cache() -> None:
    project_board_summary_cache.stop()
