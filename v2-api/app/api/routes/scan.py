from fastapi import APIRouter, Request

from app.core.responses import ok

router = APIRouter(prefix="/projects/{project_id}")


@router.post("/scan/import")
def import_scan(project_id: int, request: Request):
    return ok(request, {"project_id": project_id, "job_id": 0, "kind": "scan", "status": "pending"})


@router.get("/scan/imports/{job_id}")
def get_scan_import(project_id: int, job_id: int, request: Request):
    return ok(request, {"project_id": project_id, "job_id": job_id, "status": "placeholder"})


@router.get("/groups")
def list_project_groups(project_id: int, request: Request):
    return ok(request, {"project_id": project_id, "items": []})

