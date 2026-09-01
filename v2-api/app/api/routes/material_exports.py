from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from app.api.routes.auth import require_admin
from app.api.schemas.material_export import (
    FileAcknowledgeRequest,
    LeaseRequest,
    ReleaseRequest,
    ReserveJobRequest,
    TaskIdsRequest,
    TerminalSettingRequest,
)
from app.core.responses import error_response, ok
from app.database import SessionLocal
from app.services.local_simulation import current_team_id
from app.services.material_export import (
    MaterialExportBusy,
    MaterialExportCompletedCannotRelease,
    MaterialExportError,
    MaterialExportFileMismatch,
    MaterialExportLeaseMismatch,
    MaterialExportPoolShortage,
    MaterialExportProjectMismatch,
    MaterialExportSnapshotChanged,
    PostgresMaterialExportService,
)
from app.services.material_export_stream import (
    MaterialExportFileSnapshot,
    MaterialExportObjectMismatch,
    MaterialExportOssUnavailable,
    build_export_stream,
)


router = APIRouter(prefix="/material-exports")


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    team_id: str
    user_id: UUID | None
    actor: str


def admin_identity(
    *, request: Request, admin_payload: Mapping[str, object]
) -> AdminIdentity:
    del request
    raw_user_id = str(admin_payload.get("user_id") or "").strip()
    try:
        user_id = UUID(raw_user_id) if raw_user_id else None
    except ValueError:
        user_id = None
    actor = str(
        admin_payload.get("username") or admin_payload.get("sub") or "admin"
    ).strip() or "admin"
    return AdminIdentity(
        team_id=current_team_id(),
        user_id=user_id,
        actor=actor,
    )


def _service(session, identity: AdminIdentity) -> PostgresMaterialExportService:
    return PostgresMaterialExportService(
        session,
        team_id=identity.team_id,
        actor_id=identity.user_id,
        actor=identity.actor,
    )


def _error(request: Request, exc: Exception):
    if isinstance(exc, MaterialExportPoolShortage):
        return error_response(
            request,
            exc.code,
            str(exc),
            details={
                "total_shortage": exc.total_shortage,
                "terminal_shortages": exc.terminal_shortages,
            },
            status_code=409,
        )
    if isinstance(exc, MaterialExportBusy):
        return error_response(request, exc.code, str(exc), status_code=423)
    if isinstance(
        exc,
        (
            MaterialExportProjectMismatch,
            MaterialExportSnapshotChanged,
            MaterialExportLeaseMismatch,
            MaterialExportFileMismatch,
            MaterialExportCompletedCannotRelease,
        ),
    ):
        return error_response(request, exc.code, str(exc), status_code=409)
    if isinstance(exc, (MaterialExportOssUnavailable, MaterialExportObjectMismatch)):
        return error_response(
            request,
            "oss_internal_unavailable",
            str(exc),
            status_code=502,
        )
    if isinstance(exc, MaterialExportError):
        return error_response(request, exc.code, str(exc), status_code=400)
    if isinstance(exc, (ValueError, TypeError)):
        message = str(exc) or "请求数据无效"
        status = 404 if "不存在" in message or "不属于" in message else 400
        return error_response(
            request,
            "material_export_not_found" if status == 404 else "invalid_request",
            message,
            status_code=status,
        )
    raise exc


def authorize_material_export_stream(
    *, identity: AdminIdentity, job_id: str, file_id: str, lease_token: str
) -> MaterialExportFileSnapshot:
    with SessionLocal() as session:
        return _service(session, identity).authorize_stream(
            job_id=job_id,
            file_id=file_id,
            lease_token=lease_token,
        )


def record_material_export_stream_event(
    *, identity: AdminIdentity, file_id: str, outcome: str, byte_size: int
) -> None:
    with SessionLocal.begin() as session:
        _service(session, identity).record_stream_event(
            file_id=file_id,
            outcome=outcome,
            byte_size=byte_size,
        )


@router.post("/terminal-summaries")
def terminal_summaries(
    payload: TaskIdsRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal() as session:
            rows = _service(session, identity).list_terminal_summaries(
                task_ids=payload.task_ids
            )
            return ok(request, [asdict(row) for row in rows])
    except Exception as exc:
        return _error(request, exc)


@router.patch("/terminal-settings/{task_id}")
def update_terminal_setting(
    task_id: str,
    payload: TerminalSettingRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            row = _service(session, identity).set_requested_collector_count(
                task_id=task_id,
                count=payload.requested_collector_count,
            )
            return ok(request, asdict(row))
    except Exception as exc:
        return _error(request, exc)


@router.post("/preflight")
def preflight(
    payload: TaskIdsRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal() as session:
            result = _service(session, identity).preflight(task_ids=payload.task_ids)
            return ok(request, asdict(result))
    except Exception as exc:
        return _error(request, exc)


@router.post("/jobs")
def reserve_job(
    payload: ReserveJobRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            result = _service(session, identity).reserve_job(
                preflight_fingerprint=payload.preflight_fingerprint.lower(),
                task_ids=payload.task_ids,
            )
            return ok(request, asdict(result))
    except Exception as exc:
        return _error(request, exc)


@router.get("/jobs/{job_id}")
def job_detail(
    job_id: str,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal() as session:
            result = _service(session, identity).job_detail(job_id=job_id)
            return ok(request, asdict(result))
    except Exception as exc:
        return _error(request, exc)


@router.post("/jobs/{job_id}/lease")
def acquire_lease(
    job_id: str,
    payload: LeaseRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            lease = _service(session, identity).acquire_lease(
                job_id=job_id,
                owner_token=payload.owner_token,
            )
            return ok(
                request,
                {
                    "scope": lease.scope,
                    "job_id": str(lease.job_id),
                    "expires_at": lease.expires_at.isoformat(),
                },
            )
    except Exception as exc:
        return _error(request, exc)


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(
    job_id: str,
    payload: LeaseRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            lease = _service(session, identity).heartbeat(
                job_id=job_id,
                owner_token=payload.owner_token,
            )
            return ok(request, {"expires_at": lease.expires_at.isoformat()})
    except Exception as exc:
        return _error(request, exc)


@router.post("/jobs/{job_id}/pause")
def pause(
    job_id: str,
    payload: LeaseRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            _service(session, identity).pause(
                job_id=job_id,
                owner_token=payload.owner_token,
            )
            return ok(request, {"status": "paused"})
    except Exception as exc:
        return _error(request, exc)


@router.post("/jobs/{job_id}/files/{file_id}/ack")
def acknowledge_file(
    job_id: str,
    file_id: str,
    payload: FileAcknowledgeRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            row = _service(session, identity).ack_file(
                job_id=job_id,
                file_id=file_id,
                byte_size=payload.byte_size,
                sha256=payload.sha256,
            )
            return ok(request, {"file_id": str(row.id), "status": row.status})
    except Exception as exc:
        return _error(request, exc)


@router.post("/jobs/{job_id}/terminals/{terminal_id}/complete")
def complete_terminal(
    job_id: str,
    terminal_id: str,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            _service(session, identity).mark_terminal_completed(
                job_id=job_id, terminal_id=terminal_id
            )
            return ok(request, {"status": "completed"})
    except Exception as exc:
        return _error(request, exc)


@router.post("/jobs/{job_id}/release")
def release(
    job_id: str,
    payload: ReleaseRequest,
    request: Request,
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        with SessionLocal.begin() as session:
            _service(session, identity).cancel_and_release(
                job_id=job_id,
                terminal_ids=payload.terminal_ids,
                reason=payload.reason,
            )
            return ok(request, {"status": "cancelled_released"})
    except Exception as exc:
        return _error(request, exc)


@router.get("/jobs/{job_id}/files/{file_id}")
def stream_file(
    job_id: str,
    file_id: str,
    request: Request,
    lease_token: str = Header(alias="X-Material-Export-Lease"),
    admin_payload: dict = Depends(require_admin),
):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    try:
        file_snapshot = authorize_material_export_stream(
            identity=identity,
            job_id=job_id,
            file_id=file_id,
            lease_token=lease_token,
        )
        stream = build_export_stream(
            file_snapshot,
            on_complete=lambda sent: record_material_export_stream_event(
                identity=identity,
                file_id=file_id,
                outcome="finished",
                byte_size=sent,
            ),
            on_abort=lambda sent: record_material_export_stream_event(
                identity=identity,
                file_id=file_id,
                outcome="aborted",
                byte_size=sent,
            ),
        )
        return StreamingResponse(
            stream,
            media_type=file_snapshot.content_type,
            headers={
                "Content-Length": str(file_snapshot.byte_size),
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        return _error(request, exc)
