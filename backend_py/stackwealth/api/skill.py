"""/api/skill — direct skill endpoints used by canvas widgets (bypass agent)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db import get_plan, save_plan
from ..skills.allocate import compute_allocation
from ..skills.allocate import recommend as allocate_recommend
from ..skills.cashflow import project as cashflow_project
from ..skills.cfp import run_cfp
from ..skills.debt import paydown as debt_paydown
from ..skills.freedom import score as freedom_score
from ..skills.risk import assess as risk_assess
from ..skills.scenario import run_monte_carlo
from ..skills.suggestions import compute_suggestions
from ..skills.tax import harvest as tax_harvest

router = APIRouter()


def _json(data: Any) -> JSONResponse:
    if hasattr(data, "model_dump"):
        return JSONResponse(content=data.model_dump(mode="json"))
    return JSONResponse(content=data)


@router.post("/risk/{id}")
async def risk(id: str, request: Request) -> JSONResponse:
    body = await request.json() if (await request.body()) else {}
    r = await risk_assess({"household_id": id, "willingness": body.get("willingness")})
    plan = await get_plan(id)
    if plan and not isinstance(r, dict):
        plan.computed.risk_profile = r
        plan.computed.allocation = compute_allocation(plan)
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return _json(r)


@router.post("/freedom/{id}")
async def freedom(id: str) -> JSONResponse:
    r = await freedom_score({"household_id": id})
    plan = await get_plan(id)
    if plan and not isinstance(r, dict):
        plan.computed.freedom_score = r
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return _json(r)


@router.post("/allocate/{id}")
async def allocate(id: str) -> JSONResponse:
    r = await allocate_recommend({"household_id": id})
    plan = await get_plan(id)
    if plan and not isinstance(r, dict):
        plan.computed.allocation = r
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return _json(r)


@router.post("/tax/{id}")
async def tax(id: str) -> JSONResponse:
    r = await tax_harvest({"household_id": id})
    plan = await get_plan(id)
    if plan and not isinstance(r, dict):
        plan.computed.tax = r
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return _json(r)


@router.post("/cashflow/{id}")
async def cashflow(id: str, request: Request) -> JSONResponse:
    body = await request.json() if (await request.body()) else {}
    r = await cashflow_project(
        {"household_id": id, "horizon_years": body.get("horizon_years") or 45}
    )
    plan = await get_plan(id)
    if plan and not isinstance(r, dict):
        plan.computed.cashflow = r
        plan.computed.cash_flow_table = r.rows
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return _json(r)


@router.post("/montecarlo/{id}")
async def montecarlo(id: str, request: Request) -> JSONResponse:
    body = await request.json() if (await request.body()) else {}
    r = await run_monte_carlo({"household_id": id, "paths": body.get("paths") or 2000})
    plan = await get_plan(id)
    if plan and not isinstance(r, dict):
        plan.computed.monte_carlo = r
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return _json(r)


@router.post("/debt/{id}")
async def debt(id: str) -> JSONResponse:
    r = await debt_paydown({"household_id": id})
    plan = await get_plan(id)
    if plan and not isinstance(r, dict):
        plan.computed.debt_paydown = r
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return _json(r)


@router.post("/cfp/{id}")
@router.get("/cfp/{id}")
async def cfp(id: str) -> JSONResponse:
    """Direct CFP-engine endpoint — bypasses the agent. Returns the full
    Excel-faithful plan: summary, goal_blocks (with computation_trace per
    goal), retirement, insurance, yoy_cashflow, and the top-level
    computation_trace. Use this for quick verification or for non-chat
    surfaces that want the math without the agent in the loop."""
    return _json(await run_cfp(id))


@router.post("/suggestions/{id}")
@router.get("/suggestions/{id}")
async def suggestions(id: str) -> JSONResponse:
    """AI 'suggested' optimisation layer — the six-lever engine that proposes
    how to close goal/retirement/cashflow gaps (increase SIP, give a goal more
    time, trim its value, increase income, liquidate a hard asset, or fold in a
    lumpsum). Computes, persists to `plan.computed.suggestions`, and returns the
    snapshot. Powers the 'Suggested ___' canvas sections and the report."""
    plan = await get_plan(id)
    if not plan:
        return _json({"error": "household_not_found"})
    snapshot = compute_suggestions(plan)
    plan.computed.suggestions = snapshot
    try:
        await save_plan(plan)
    except Exception:
        pass  # returning the fresh snapshot matters more than persisting it
    return _json(snapshot)
