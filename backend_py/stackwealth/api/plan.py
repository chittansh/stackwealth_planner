"""/api/plan — read + direct mutation endpoints for the canvas."""
from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..db import get_plan, save_plan
from ..skills.scenario import apply_add, apply_assumption, apply_remove, apply_set
from ..types import empty_plan_state

router = APIRouter()


def _json(data: Any, status: int = 200) -> Response:
    """Serialize Pydantic models with mode='json' so nulls survive intact for
    the TS frontend that distinguishes null from undefined."""
    if hasattr(data, "model_dump"):
        return JSONResponse(content=data.model_dump(mode="json"), status_code=status)
    return JSONResponse(content=data, status_code=status)


@router.get("/{id}")
async def read_plan(id: str) -> Response:
    # Graceful-degrade on transient PG flap (mesh dropping connections
    # mid-operation). The retry loop inside get_plan already burns its
    # budget; if it raises ConnectionError we surface a 503 with a
    # Retry-After header so the FE polls back instead of showing a
    # broken state from the 500 traceback. Brief outages become a
    # short loading state, not a hard error.
    try:
        plan = await get_plan(id)
    except ConnectionError:
        return JSONResponse(
            content={"error": "database_unavailable", "retry_after_seconds": 2},
            status_code=503,
            headers={"Retry-After": "2"},
        )
    if not plan:
        plan = empty_plan_state(id)
        try:
            await save_plan(plan)
        except ConnectionError:
            # Save failed but we can still hand back the in-memory blank
            # so the canvas renders; next mutation will retry the save.
            pass
    return _json(plan)


@router.post("")
async def create_or_upsert(request: Request) -> Response:
    body = await request.json() if (await request.body()) else {}
    new_id: str = body.get("id") or f"h_{uuid4().hex[:8]}"
    name: Optional[str] = body.get("name")
    advisor_id: Optional[str] = body.get("advisor_id")
    existing = await get_plan(new_id)
    if existing:
        if name:
            existing.personal_details.full_name = name
        if advisor_id:
            existing.__pydantic_extra__ = (existing.__pydantic_extra__ or {}) | {"advisor_id": advisor_id}  # type: ignore[attr-defined]
        await save_plan(existing)
        return _json({"ok": True, "id": new_id, "created": False})
    plan = empty_plan_state(new_id)
    if name:
        plan.personal_details.full_name = name
    if advisor_id:
        plan.__pydantic_extra__ = (plan.__pydantic_extra__ or {}) | {"advisor_id": advisor_id}  # type: ignore[attr-defined]
    await save_plan(plan)
    return _json({"ok": True, "id": new_id, "created": True})


@router.post("/{id}/set")
async def set_path(id: str, request: Request) -> Response:
    b = await request.json()
    return _json(
        await apply_set(
            {
                "household_id": id,
                "path": b["path"],
                "value": b.get("value"),
                "source_type": b.get("source_type") or "user",
            }
        )
    )


@router.post("/{id}/add")
async def add_row(id: str, request: Request) -> Response:
    b = await request.json()
    return _json(
        await apply_add(
            {
                "household_id": id,
                "path": b["path"],
                "row": b.get("row"),
                "source_type": "user",
            }
        )
    )


@router.post("/{id}/remove")
async def remove_row(id: str, request: Request) -> Response:
    b = await request.json()
    return _json(
        await apply_remove({"household_id": id, "path": b["path"], "id": b["id"]})
    )


@router.post("/{id}/assumption")
async def assumption(id: str, request: Request) -> Response:
    b = await request.json()
    return _json(
        await apply_assumption(
            {"household_id": id, "path": b["path"], "value": b.get("value")}
        )
    )
