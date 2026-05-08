"""/api/scenario — Plan A/B compare endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db import get_plan, save_plan
from ..skills.scenario import diff, pin

router = APIRouter()


def _json(data: Any) -> JSONResponse:
    if hasattr(data, "model_dump"):
        return JSONResponse(content=data.model_dump(mode="json"))
    return JSONResponse(content=data)


@router.post("/{id}/pin")
async def pin_scenario(id: str, request: Request) -> JSONResponse:
    body = await request.json()
    return _json(
        await pin(
            {
                "household_id": id,
                "label": body["label"],
                "mutation": body.get("mutation"),
            }
        )
    )


@router.post("/{id}/diff")
async def diff_scenarios(id: str, request: Request) -> JSONResponse:
    body = await request.json()
    return _json(await diff({"household_id": id, "a": body["a"], "b": body["b"]}))


@router.post("/{id}/toggle")
async def toggle(id: str, request: Request) -> JSONResponse:
    body = await request.json()
    plan = await get_plan(id)
    if not plan:
        return JSONResponse(content={"ok": False}, status_code=404)
    s = set(plan.active_scenario_ids)
    if body.get("active"):
        s.add(body["id"])
    else:
        s.discard(body["id"])
    plan.active_scenario_ids = list(s)[-3:]
    await save_plan(plan)
    return _json({"ok": True})


@router.post("/{id}/clear")
async def clear(id: str) -> JSONResponse:
    plan = await get_plan(id)
    if not plan:
        return JSONResponse(content={"ok": False}, status_code=404)
    plan.scenarios = []
    plan.active_scenario_ids = []
    await save_plan(plan)
    return _json({"ok": True})
