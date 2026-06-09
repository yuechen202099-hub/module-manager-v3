from fastapi import APIRouter, Request

from app.core.responses import ok

router = APIRouter(prefix="/projects/{project_id}/catalog")


@router.post("/total/import")
def import_total_catalog(project_id: int, request: Request):
    return ok(request, {"project_id": project_id, "job_id": 0, "kind": "total_catalog", "status": "pending"})


@router.post("/stage/import")
def import_stage_catalog(project_id: int, request: Request):
    return ok(request, {"project_id": project_id, "job_id": 0, "kind": "stage_catalog", "status": "pending"})


@router.get("/imports/{job_id}")
def get_catalog_import(project_id: int, job_id: int, request: Request):
    return ok(request, {"project_id": project_id, "job_id": job_id, "status": "placeholder"})

