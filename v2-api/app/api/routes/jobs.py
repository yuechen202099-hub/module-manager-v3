from fastapi import APIRouter, Request

from app.core.responses import ok

router = APIRouter(prefix="/jobs")


@router.get("/{job_id}")
def get_job(job_id: int, request: Request):
    return ok(request, {"job_id": job_id, "status": "placeholder"})

