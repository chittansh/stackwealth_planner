"""/api/excel — the CFP Excel engine.

  POST /api/excel/{id}/compute   run the firm workbook for a household → outputs
  GET  /api/excel/{id}/outputs   cached structured outputs (computes if needed)
  GET  /api/excel/{id}.xlsx      download the populated, recalculated workbook
                                 (this is what the UI "Open computed Excel" button hits)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from ..db import get_computed_workbook, get_source_workbook
from ..excel_engine.engine import render_sheets
from ..skills.excel_plan import NoWorkbookError, get_or_compute_outputs, run_excel_plan

router = APIRouter()


async def _ensure_computed(id: str) -> bytes | None:
    """Return the computed workbook bytes, computing on demand if a source
    upload exists. None if nothing to compute."""
    computed, _ = await get_computed_workbook(id)
    if computed is None and await get_source_workbook(id):
        await run_excel_plan(id)
        computed, _ = await get_computed_workbook(id)
    return computed


@router.post("/{id}/compute")
async def compute(id: str) -> JSONResponse:
    try:
        outputs = await run_excel_plan(id)
    except NoWorkbookError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # recalc / engine failure
        raise HTTPException(status_code=500, detail=f"Excel engine failed: {e}")
    return JSONResponse({"ok": True, "outputs": outputs})


@router.get("/{id}/outputs")
async def outputs(id: str) -> JSONResponse:
    data = await get_or_compute_outputs(id)
    if data is None:
        raise HTTPException(
            status_code=404, detail="No CFP workbook uploaded for this household."
        )
    return JSONResponse({"ok": True, "outputs": data})


@router.get("/{id}/grid")
async def grid(id: str) -> JSONResponse:
    """Computed workbook rendered as grid data for the in-browser viewer — the
    recalculated sheets shown inside the app (no desktop spreadsheet needed)."""
    try:
        computed = await _ensure_computed(id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel engine failed: {e}")
    if computed is None:
        raise HTTPException(
            status_code=404, detail="No CFP workbook uploaded for this household."
        )
    return JSONResponse({"ok": True, "sheets": render_sheets(computed)})


@router.get("/{id}.xlsx")
async def download(id: str) -> Response:
    """Return the populated, recalculated workbook for download. The in-app
    viewer uses /grid; this is for users who want the raw file."""
    try:
        computed = await _ensure_computed(id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel engine failed: {e}")
    if computed is None:
        raise HTTPException(
            status_code=404, detail="No CFP workbook available for this household."
        )
    return Response(
        content=computed,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="cfp_plan_{id}.xlsx"',
        },
    )
