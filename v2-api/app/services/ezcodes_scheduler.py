from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.services.ezcodes_sync import (
    EzcodesBackend,
    EzcodesCloudBaseBackend,
    EzcodesCredentials,
    EzcodesError,
    download_scan_data_preview,
)
from app.services.local_simulation import apply_synced_scan_records


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class EzcodesSyncOptions:
    max_files: int
    max_records_per_file: int


class EzcodesSyncManager:
    def __init__(self, backend: EzcodesBackend | None = None) -> None:
        self.backend = backend or EzcodesCloudBaseBackend()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._last_result: dict[str, Any] | None = None
        self._last_error: str = ""
        self._last_started_at: str = ""
        self._last_finished_at: str = ""
        self._last_trigger: str = ""

    def set_backend(self, backend: EzcodesBackend) -> None:
        with self._lock:
            self.backend = backend

    def configured_credentials(self) -> EzcodesCredentials | None:
        if not settings.ezcodes_access_token or not settings.ezcodes_team_id:
            return None
        return EzcodesCredentials(
            access_token=settings.ezcodes_access_token,
            team_id=settings.ezcodes_team_id,
            env_id=settings.ezcodes_env_id,
            endpoint=settings.ezcodes_endpoint,
        )

    def default_options(self) -> EzcodesSyncOptions:
        return EzcodesSyncOptions(
            max_files=max(1, settings.ezcodes_sync_max_files),
            max_records_per_file=max(1, settings.ezcodes_sync_max_records_per_file),
        )

    def trigger(
        self,
        credentials: EzcodesCredentials | None = None,
        options: EzcodesSyncOptions | None = None,
        trigger: str = "manual",
    ) -> dict[str, Any]:
        credentials = credentials or self.configured_credentials()
        if credentials is None:
            raise EzcodesError("Ezcodes credentials are not configured.")
        options = options or self.default_options()
        with self._lock:
            if self._running:
                return self.status()
            self._running = True
            self._last_error = ""
            self._last_started_at = utc_now()
            self._last_trigger = trigger
        try:
            result = download_scan_data_preview(
                self.backend,
                credentials,
                max_files=options.max_files,
                max_records_per_file=options.max_records_per_file,
            )
            apply_result = apply_synced_scan_records(result.get("records", []))
            result["apply_result"] = apply_result
            with self._lock:
                self._last_result = result
                self._last_finished_at = utc_now()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._last_finished_at = utc_now()
            raise
        finally:
            with self._lock:
                self._running = False
        return self.status()

    def start_periodic(self) -> None:
        if not settings.ezcodes_sync_enabled:
            return
        if self.configured_credentials() is None:
            return
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(target=self._periodic_loop, name="ezcodes-sync", daemon=True)
            self._worker.start()

    def stop_periodic(self) -> None:
        self._stop.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=2)

    def status(self) -> dict[str, Any]:
        with self._lock:
            result = self._last_result or {}
            return {
                "enabled": settings.ezcodes_sync_enabled,
                "configured": self.configured_credentials() is not None,
                "running": self._running,
                "interval_seconds": settings.ezcodes_sync_interval_seconds,
                "last_trigger": self._last_trigger,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "last_error": self._last_error,
                "last_downloaded_records": result.get("downloaded_records", 0),
                "last_resolved_image_urls": result.get("resolved_image_urls", 0),
                "last_tested_files": result.get("tested_files", 0),
                "last_applied_records": (result.get("apply_result") or {}).get("applied_records", 0),
                "last_unmatched_records": (result.get("apply_result") or {}).get("unmatched_records", 0),
                "last_skipped_duplicates": (result.get("apply_result") or {}).get("skipped_duplicates", 0),
            }

    def _periodic_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.trigger(trigger="scheduled")
            except Exception:
                pass
            interval = max(60, settings.ezcodes_sync_interval_seconds)
            self._stop.wait(interval)


sync_manager = EzcodesSyncManager()
