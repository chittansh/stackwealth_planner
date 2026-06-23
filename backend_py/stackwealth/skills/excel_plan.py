"""Excel-engine skill — run the firm's CFP workbook for a household.

Loads the household's stored firm-template upload, pours its inputs into the
pristine master, recalculates with headless LibreOffice, persists the populated
workbook + structured outputs, and mirrors the outputs onto ``plan.computed.
excel_outputs`` so the canvas / report / agent read the firm's own numbers.

The heavy LibreOffice subprocess is run in a worker thread so it never blocks
the event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from ..db import (
    get_computed_workbook,
    get_plan,
    get_source_workbook,
    save_computed_workbook,
    save_plan,
)
from ..excel_engine.engine import compute_from_upload


class NoWorkbookError(RuntimeError):
    """Raised when a household has no stored firm-template upload to compute."""


async def run_excel_plan(household_id: str) -> dict[str, Any]:
    """Compute the CFP plan for ``household_id`` from its stored upload.

    Returns the structured outputs ({"scalars":..., "tables":...}). Raises
    NoWorkbookError if the household has no source workbook on file.
    """
    source = await get_source_workbook(household_id)
    if not source:
        raise NoWorkbookError(
            f"No firm-template workbook stored for household {household_id}. "
            "Upload the CFP input .xlsx first."
        )

    # LibreOffice recalc is blocking + CPU/IO heavy → offload to a thread.
    populated, outputs = await asyncio.to_thread(compute_from_upload, source)

    await save_computed_workbook(household_id, populated, outputs)

    # Mirror onto the plan's computed snapshot so the rest of the app sees it.
    plan = await get_plan(household_id)
    if plan is not None:
        plan.computed.excel_outputs = outputs
        # Keep the headline number in sync for cards that read it directly.
        nw = (outputs.get("scalars") or {}).get("net_worth")
        if isinstance(nw, (int, float)):
            plan.computed.headline_amount_at_horizon = float(nw)
        await save_plan(plan)

    return outputs


async def get_or_compute_outputs(household_id: str) -> Optional[dict[str, Any]]:
    """Return cached engine outputs, computing them if a source workbook exists
    but no computed result is cached yet. Returns None if nothing to compute."""
    _, outputs = await get_computed_workbook(household_id)
    if outputs:
        return outputs
    try:
        return await run_excel_plan(household_id)
    except NoWorkbookError:
        return None
