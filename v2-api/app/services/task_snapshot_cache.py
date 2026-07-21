from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from app.core.config import settings

TaskSnapshotBuilder = Callable[[str], dict[str, Any]]
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


def _normalize_team_id(team_id: str) -> str:
    return str(team_id or "").strip() or "default-team"


def _team_file_key(team_id: str) -> str:
    normalized = _normalize_team_id(team_id)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", normalized).strip(".-") or "team"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{slug[:80]}-{digest}"


def default_task_snapshot_cache_root() -> Path:
    configured = settings.task_snapshot_cache_path.strip()
    if configured:
        return Path(configured)
    auth_users_path = settings.auth_users_path.strip()
    if auth_users_path:
        return Path(auth_users_path).resolve().parent / "task-snapshot-cache"
    return Path.cwd().resolve() / "data" / "task-snapshot-cache"


class TaskSnapshotCache:
    def __init__(
        self,
        *,
        cache_root: Path | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        configured = interval_seconds if interval_seconds is not None else settings.task_snapshot_cache_seconds
        self.interval_seconds = max(30, int(configured))
        self.enabled = settings.task_snapshot_cache_enabled if enabled is None else bool(enabled)
        self.cache_root = cache_root or default_task_snapshot_cache_root()
        self._lock = threading.RLock()
        self._memory: dict[str, dict[str, Any]] = {}
        self._refreshing: set[str] = set()
        self._refresh_events: dict[str, threading.Event] = {}
        self._known_teams: set[str] = set()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None

    def get(
        self,
        team_id: str,
        builder: TaskSnapshotBuilder,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        normalized_team_id = _normalize_team_id(team_id)
        with self._lock:
            self._known_teams.add(normalized_team_id)
        if not self.enabled or force_refresh:
            return self.refresh(normalized_team_id, builder, source="refresh")
        snapshot = self._snapshot_for_team(normalized_team_id)
        if snapshot is None:
            return self.refresh(normalized_team_id, builder, source="cold")
        stale = self._is_stale(snapshot)
        if stale:
            self.refresh_async(normalized_team_id, builder)
        return self._payload_with_cache_meta(snapshot, stale=stale)

    def refresh(
        self,
        team_id: str,
        builder: TaskSnapshotBuilder,
        *,
        source: str = "refresh",
    ) -> dict[str, Any]:
        normalized_team_id = _normalize_team_id(team_id)
        with self._lock:
            self._known_teams.add(normalized_team_id)
            if normalized_team_id in self._refreshing:
                snapshot = self._snapshot_for_team(normalized_team_id)
                if snapshot is not None:
                    return self._payload_with_cache_meta(snapshot, stale=True)
                wait_event = self._refresh_events[normalized_team_id]
                owner_event = None
            else:
                owner_event = threading.Event()
                self._refresh_events[normalized_team_id] = owner_event
                self._refreshing.add(normalized_team_id)
                wait_event = None

        if wait_event is not None:
            wait_event.wait()
            snapshot = self._snapshot_for_team(normalized_team_id)
            if snapshot is not None:
                return self._payload_with_cache_meta(snapshot, stale=self._is_stale(snapshot))
            return self.refresh(normalized_team_id, builder, source=source)

        assert owner_event is not None
        try:
            payload = builder(normalized_team_id)
            if _normalize_team_id(str(payload.get("team_id") or "")) != normalized_team_id:
                raise ValueError("task snapshot team does not match requested team")
            snapshot = {
                "generated_at": _utc_now().isoformat(),
                "payload": deepcopy(payload),
                "source": source,
            }
            self._store_snapshot(normalized_team_id, snapshot)
            return self._payload_with_cache_meta(snapshot, stale=False)
        finally:
            with self._lock:
                self._refreshing.discard(normalized_team_id)
                if self._refresh_events.get(normalized_team_id) is owner_event:
                    self._refresh_events.pop(normalized_team_id, None)
            owner_event.set()

    def refresh_async(self, team_id: str, builder: TaskSnapshotBuilder) -> None:
        normalized_team_id = _normalize_team_id(team_id)
        with self._lock:
            self._known_teams.add(normalized_team_id)
            if normalized_team_id in self._refreshing:
                return
            self._refreshing.add(normalized_team_id)

        def runner() -> None:
            try:
                payload = builder(normalized_team_id)
                if _normalize_team_id(str(payload.get("team_id") or "")) != normalized_team_id:
                    raise ValueError("task snapshot team does not match requested team")
                self._store_snapshot(
                    normalized_team_id,
                    {
                        "generated_at": _utc_now().isoformat(),
                        "payload": deepcopy(payload),
                        "source": "background",
                    },
                )
            except Exception:
                logger.exception("Task snapshot background refresh failed for team %s", normalized_team_id)
            finally:
                with self._lock:
                    self._refreshing.discard(normalized_team_id)
                    event = self._refresh_events.pop(normalized_team_id, None)
                    if event is not None:
                        event.set()

        threading.Thread(
            target=runner,
            name=f"task-snapshot-cache-{_team_file_key(normalized_team_id)}",
            daemon=True,
        ).start()

    def start(self, builder: TaskSnapshotBuilder, team_ids: Iterable[str] = ()) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._known_teams.update(_normalize_team_id(team_id) for team_id in team_ids)
            if self._worker and self._worker.is_alive():
                return
            self._stop_event.clear()

        def loop() -> None:
            while not self._stop_event.is_set():
                with self._lock:
                    teams = tuple(self._known_teams)
                for current_team_id in teams:
                    if self._stop_event.is_set():
                        break
                    try:
                        self.refresh(current_team_id, builder, source="scheduled")
                    except Exception:
                        logger.exception("Task snapshot scheduled refresh failed for team %s", current_team_id)
                self._stop_event.wait(self.interval_seconds)

        self._worker = threading.Thread(target=loop, name="task-snapshot-cache", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=2)

    def invalidate(self, team_id: str) -> None:
        self._discard_snapshot(_normalize_team_id(team_id))

    def _snapshot_for_team(self, team_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._memory.get(team_id)
        if snapshot is None:
            snapshot = self._load_from_file(team_id)
            if snapshot is not None:
                with self._lock:
                    self._memory[team_id] = snapshot
        if snapshot is not None and not self._snapshot_matches_team(snapshot, team_id):
            self._discard_snapshot(team_id)
            return None
        return snapshot

    def _cache_file(self, team_id: str) -> Path:
        return self.cache_root / f"tasks-{_team_file_key(team_id)}.json"

    def _load_from_file(self, team_id: str) -> dict[str, Any] | None:
        path = self._cache_file(team_id)
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

    def _snapshot_matches_team(self, snapshot: dict[str, Any], team_id: str) -> bool:
        payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
        if not isinstance(payload, dict):
            return False
        return _normalize_team_id(str(payload.get("team_id") or "")) == team_id

    def _discard_snapshot(self, team_id: str) -> None:
        with self._lock:
            self._memory.pop(team_id, None)
        try:
            self._cache_file(team_id).unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to discard task snapshot cache for team %s", team_id)

    def _store_snapshot(self, team_id: str, snapshot: dict[str, Any]) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        path = self._cache_file(team_id)
        tmp_path = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp_path.replace(path)
        with self._lock:
            self._memory[team_id] = snapshot

    def _is_stale(self, snapshot: dict[str, Any]) -> bool:
        generated_at = _parse_iso_datetime(str(snapshot.get("generated_at") or ""))
        if generated_at is None:
            return True
        return (_utc_now() - generated_at).total_seconds() >= self.interval_seconds

    def _payload_with_cache_meta(self, snapshot: dict[str, Any], *, stale: bool) -> dict[str, Any]:
        payload = deepcopy(snapshot.get("payload") or {})
        payload["cache"] = {
            "type": "task_snapshot",
            "source": snapshot.get("source") or "memory",
            "generated_at": snapshot.get("generated_at") or "",
            "stale": stale,
            "refresh_interval_seconds": self.interval_seconds,
        }
        return payload


task_snapshot_cache = TaskSnapshotCache()


def stop_task_snapshot_cache() -> None:
    task_snapshot_cache.stop()
