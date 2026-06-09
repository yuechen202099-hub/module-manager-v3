from fastapi import APIRouter, HTTPException, Query, Request

from app.core.responses import ok
from app.services.local_simulation import bootstrap_local_simulation, get_group, get_state, list_groups

router = APIRouter(prefix="/local-test")


@router.post("/bootstrap")
def bootstrap(request: Request):
    state = bootstrap_local_simulation()
    return ok(request, {"summary": state["summary"], "paths": state["paths"]})


@router.get("/summary")
def summary(request: Request):
    state = get_state()
    return ok(request, {"summary": state["summary"], "paths": state["paths"]})


@router.get("/groups")
def groups(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
):
    return ok(request, list_groups(limit=limit, offset=offset, status=status))


@router.get("/groups/{group_id}")
def group_detail(group_id: str, request: Request):
    group = get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return ok(request, group)
