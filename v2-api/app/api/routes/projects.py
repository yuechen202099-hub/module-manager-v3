from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.core.responses import ok
from app.schemas.project import ProjectCreate, ProjectWorkItemSchemaUpdate
from app.services.platform.catalog import (
    ProjectConfigurationError,
    ProjectNotFound,
    ProjectValidationError,
    create_project_draft,
    get_project_overview,
    get_project_section,
    get_project_workflow,
    list_project_modules,
    list_project_overviews,
    reset_project_workflow,
    update_project_workflow,
    update_project_work_item_schema,
)
from app.services.platform.persistence import build_platform_persistence_status
from app.services.platform.config_persistence_contract import build_project_config_persistence_contract
from app.services.platform.handoff_readiness import build_platform_handoff_readiness
from app.services.platform.migration_readiness import build_platform_migration_readiness
from app.services.platform.readiness import build_project_readiness, build_project_readiness_summary
from app.services.platform.templates import (
    build_project_template_workbook,
    build_project_template_preview,
    create_import_work_order_task,
    create_project_template_import_batch,
    create_project_template_import_draft,
    delete_platform_construction_work_order_photo,
    execute_import_work_order_task,
    get_import_work_order_task,
    list_platform_construction_work_orders,
    list_platform_review_work_orders,
    get_project_template_import_batch,
    project_template_filename,
    rollback_import_work_order_task,
    review_platform_work_order,
    save_platform_construction_work_order_collection,
    upload_platform_construction_work_order_photo,
    validate_project_template_workbook,
)

router = APIRouter(prefix="/projects")


def _project_overview_or_404(project_id: str):
    try:
        return get_project_overview(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")


def _project_section_or_404(project_id: str, section: str):
    try:
        return get_project_section(project_id, section)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project section not found")


@router.get("")
def list_projects(request: Request):
    try:
        items = list_project_overviews()
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, {"total": len(items), "items": items})


@router.get("/readiness/summary")
def get_project_readiness_summary(request: Request):
    try:
        summary = build_project_readiness_summary()
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, summary)


@router.get("/handoff/readiness")
def get_platform_handoff_readiness(request: Request):
    try:
        readiness = build_platform_handoff_readiness()
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, readiness)


@router.post("")
def create_project(payload: ProjectCreate, request: Request):
    try:
        project = create_project_draft(
            name=payload.name,
            description=payload.description or "",
            module_ids=payload.module_ids,
            work_item_schema=payload.work_item_schema.model_dump() if payload.work_item_schema else None,
        )
    except ProjectValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, project)


@router.patch("/{project_id}/work-item-schema")
def update_project_schema(project_id: str, payload: ProjectWorkItemSchemaUpdate, request: Request):
    try:
        project = update_project_work_item_schema(project_id, payload.model_dump())
    except ProjectValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, project)


@router.get("/{project_id}/workflow")
def get_project_workflow_route(project_id: str, request: Request):
    try:
        workflow = get_project_workflow(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, workflow)


@router.put("/{project_id}/workflow")
def update_project_workflow_route(project_id: str, payload: dict, request: Request):
    try:
        workflow = update_project_workflow(project_id, payload, actor=str(payload.get("actor") or ""))
    except ProjectValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, workflow)


@router.post("/{project_id}/workflow/reset")
def reset_project_workflow_route(project_id: str, payload: dict, request: Request):
    try:
        workflow = reset_project_workflow(project_id, actor=str(payload.get("actor") or ""))
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, workflow)


@router.get("/{project_id}/persistence/contract")
def get_project_config_persistence_contract(project_id: str, request: Request):
    try:
        contract = build_project_config_persistence_contract(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, contract)


@router.get("/{project_id}/readiness")
def get_project_readiness(project_id: str, request: Request):
    try:
        readiness = build_project_readiness(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, readiness)


@router.get("/{project_id}/progress")
def get_project_progress(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "progress"))


@router.get("/{project_id}/delivery")
def get_project_delivery(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "delivery"))


@router.get("/{project_id}/field")
def get_project_field(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "field"))


@router.get("/{project_id}/review")
def get_project_review(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "review"))


@router.get("/{project_id}/risks")
def get_project_risks(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "risks"))


@router.get("/{project_id}/tasks")
def get_project_tasks(project_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, "tasks"))


@router.get("/{project_id}/modules")
def list_project_module_definitions(project_id: str, request: Request):
    try:
        items = list_project_modules(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, {"project_id": project_id, "total": len(items), "items": items})


@router.get("/{project_id}/modules/{module_id}")
def get_project_module(project_id: str, module_id: str, request: Request):
    return ok(request, _project_section_or_404(project_id, module_id))


@router.get("/{project_id}/templates/{template_type}")
def download_project_template(project_id: str, template_type: str):
    try:
        content = build_project_template_workbook(project_id, template_type)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project template not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    filename = project_template_filename(project_id, template_type)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{project_id}/templates/preview")
def preview_project_templates(project_id: str, payload: dict, request: Request):
    try:
        preview = build_project_template_preview(project_id, payload.get("work_item_schema"))
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, preview)


@router.post("/{project_id}/templates/{template_type}/validate")
async def validate_project_template(project_id: str, template_type: str, request: Request, file: UploadFile = File(...)):
    try:
        content = await file.read()
        report = validate_project_template_workbook(project_id, template_type, content)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project template not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Template validation failed: {exc}")
    return ok(request, report)


@router.post("/{project_id}/templates/{template_type}/import-drafts")
async def create_project_template_import_draft_route(project_id: str, template_type: str, request: Request, file: UploadFile = File(...)):
    try:
        content = await file.read()
        draft = create_project_template_import_draft(project_id, template_type, content, file.filename or "")
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project template not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Template import draft failed: {exc}")
    return ok(request, draft)


@router.post("/{project_id}/templates/{template_type}/import-batches")
async def create_project_template_import_batch_route(
    project_id: str,
    template_type: str,
    request: Request,
    file: UploadFile = File(...),
    actor: str = Form(""),
):
    try:
        content = await file.read()
        batch = create_project_template_import_batch(project_id, template_type, content, file.filename or "", actor)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project template not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Template import batch failed: {exc}")
    return ok(request, batch)


@router.get("/{project_id}/import-batches/{batch_id}")
def get_project_template_import_batch_route(project_id: str, batch_id: str, request: Request):
    try:
        batch = get_project_template_import_batch(project_id, batch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project import batch not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, batch)


@router.post("/{project_id}/import-batches/{batch_id}/work-order-tasks")
def create_import_work_order_task_route(project_id: str, batch_id: str, payload: dict, request: Request):
    try:
        task = create_import_work_order_task(
            project_id,
            batch_id,
            actor=str(payload.get("actor") or ""),
            mode=str(payload.get("mode") or "safe_record_only"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Project import batch not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, task)


@router.get("/{project_id}/work-order-tasks/{task_id}")
def get_import_work_order_task_route(project_id: str, task_id: str, request: Request):
    try:
        task = get_import_work_order_task(project_id, task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project work order task not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, task)


@router.post("/{project_id}/work-order-tasks/{task_id}/execute")
def execute_import_work_order_task_route(project_id: str, task_id: str, payload: dict, request: Request):
    try:
        task = execute_import_work_order_task(
            project_id,
            task_id,
            actor=str(payload.get("actor") or ""),
            mode=str(payload.get("mode") or "local_platform_store"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Project work order task not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, task)


@router.post("/{project_id}/work-order-tasks/{task_id}/rollback")
def rollback_import_work_order_task_route(project_id: str, task_id: str, payload: dict, request: Request):
    try:
        task = rollback_import_work_order_task(project_id, task_id, actor=str(payload.get("actor") or ""))
    except KeyError:
        raise HTTPException(status_code=404, detail="Project work order task not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, task)


@router.get("/{project_id}/construction/work-orders")
def list_platform_construction_work_orders_route(project_id: str, request: Request):
    try:
        payload = list_platform_construction_work_orders(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, payload)


@router.get("/{project_id}/review/work-orders")
def list_platform_review_work_orders_route(project_id: str, request: Request):
    try:
        payload = list_platform_review_work_orders(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, payload)


@router.post("/{project_id}/review/work-orders/{work_order_id}/actions")
def review_platform_work_order_route(project_id: str, work_order_id: str, payload: dict, request: Request):
    try:
        work_order = review_platform_work_order(project_id, work_order_id, payload)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project review work order not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, work_order)


@router.post("/{project_id}/construction/work-orders/{work_order_id}/collection-draft")
def save_platform_construction_work_order_collection_route(project_id: str, work_order_id: str, payload: dict, request: Request):
    try:
        work_order = save_platform_construction_work_order_collection(project_id, work_order_id, payload)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project construction work order not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, work_order)


@router.post("/{project_id}/construction/work-orders/{work_order_id}/photos")
async def upload_platform_construction_work_order_photo_route(
    project_id: str,
    work_order_id: str,
    request: Request,
    file: UploadFile = File(...),
    actor: str = Form(""),
    slot: str = Form(""),
    client_photo_id: str = Form(""),
):
    try:
        content = await file.read()
        work_order = upload_platform_construction_work_order_photo(
            project_id,
            work_order_id,
            slot=slot,
            filename=file.filename or "",
            content_type=file.content_type or "",
            content=content,
            actor=actor,
            client_photo_id=client_photo_id,
        )
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project construction work order not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, work_order)


@router.delete("/{project_id}/construction/work-orders/{work_order_id}/photos/{photo_id}")
def delete_platform_construction_work_order_photo_route(project_id: str, work_order_id: str, photo_id: str, request: Request):
    try:
        work_order = delete_platform_construction_work_order_photo(project_id, work_order_id, photo_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Project construction work order photo not found")
    except ProjectConfigurationError:
        raise HTTPException(status_code=500, detail="Project configuration invalid")
    return ok(request, work_order)


@router.get("/persistence/status")
def get_platform_persistence_status(request: Request):
    return ok(request, build_platform_persistence_status())


@router.get("/persistence/migration-readiness")
def get_platform_migration_readiness(request: Request):
    return ok(request, build_platform_migration_readiness())


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    return ok(request, _project_overview_or_404(project_id))
