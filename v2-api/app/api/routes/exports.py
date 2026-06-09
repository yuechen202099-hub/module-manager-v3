from fastapi import APIRouter, Request

from app.core.responses import ok
from app.schemas.export import FinalDeliveryExportRequest, TaskDetailExportRequest

router = APIRouter(prefix="/exports")


@router.post("/task-detail")
def export_task_detail(payload: TaskDetailExportRequest, request: Request):
    return ok(request, {"job_id": 0, "kind": "task_detail", "task_id": payload.task_id, "status": "pending"})


@router.post("/final-delivery")
def export_final_delivery(payload: FinalDeliveryExportRequest, request: Request):
    return ok(request, {"job_id": 0, "kind": "final_delivery", "project_id": payload.project_id, "status": "pending"})

