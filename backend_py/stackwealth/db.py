"""
DB client — in-memory store keyed by household_id.

Mirrors the TS db/client.ts shape: getPlan / savePlan / listAllHouseholds /
seedMemory. The DATABASE_URL Postgres path is stubbed for now (in-memory is
the demo default; Day-5 task in the migration plan can wire SQLAlchemy +
JSONB schema later without touching call-sites).
"""
from __future__ import annotations

from typing import Optional

from .types import PlanState, empty_plan_state

_memory: dict[str, PlanState] = {}


def _ensure(household_id: str) -> PlanState:
    if household_id not in _memory:
        _memory[household_id] = empty_plan_state(household_id)
    return _memory[household_id]


async def get_plan(household_id: str) -> Optional[PlanState]:
    """Auto-creates an empty plan if missing — same behavior as TS."""
    return _ensure(household_id)


async def save_plan(plan: PlanState) -> None:
    _memory[plan.household_id] = plan


async def list_all_households() -> list[str]:
    return list(_memory.keys())


def seed_memory(plan: PlanState) -> None:
    _memory[plan.household_id] = plan
