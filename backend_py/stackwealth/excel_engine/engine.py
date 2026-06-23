"""CFP Excel engine — the transformer.

Flow:
    client upload (.xlsx, firm template)
        -> inject its input cells into a pristine master copy
        -> recalc with LibreOffice
        -> read the result cells back
        -> (populated workbook bytes, structured outputs)

The populated workbook is what the UI's "Open computed Excel" button downloads;
the structured outputs feed the model / Python advisory layer.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from typing import Any

import openpyxl
from openpyxl.utils import column_index_from_string

from . import cellmap
from .recalc import recalc_file

_HERE = os.path.dirname(__file__)
MASTER_PATH = os.path.join(_HERE, "master", "cfp_master.xlsx")


def _is_formula(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("=")


def inject_inputs(master_wb, upload_wb_values, upload_wb_formulas) -> int:
    """Mirror the upload's input cells into ``master_wb`` (mutated in place).

    For every INJECT tab, walk the MASTER's cell range and, for each cell that is
    NOT a formula in the master, set it to the upload's value at that coordinate
    (None if absent — which clears the master's sample data). Formula cells are
    left untouched so the firm's calculations always win. Iterating the master's
    range (not the upload's) guarantees sample data can't leak through cells the
    upload happens to omit.

    Returns the number of cells written.
    """
    written = 0
    for tab in cellmap.INJECT_TABS:
        if tab not in master_wb.sheetnames:
            continue
        ms = master_wb[tab]
        uv = upload_wb_values[tab] if tab in upload_wb_values.sheetnames else None
        uf = upload_wb_formulas[tab] if tab in upload_wb_formulas.sheetnames else None
        # Bound the sweep to the larger of the two used ranges so extra client
        # rows (more stocks / goals) are picked up too.
        max_row = ms.max_row
        max_col = ms.max_column
        if uv is not None:
            max_row = max(max_row, uv.max_row)
            max_col = max(max_col, uv.max_column)
        for r in range(1, max_row + 1):
            for c in range(1, max_col + 1):
                mcell = ms.cell(row=r, column=c)
                if _is_formula(mcell.value):
                    continue  # never overwrite a firm formula
                up_val = uv.cell(row=r, column=c).value if uv is not None else None
                # If the upload cell is itself a formula, take its cached value.
                up_is_formula = (
                    uf is not None and _is_formula(uf.cell(row=r, column=c).value)
                )
                new_val = up_val if not up_is_formula else up_val  # data_only -> cached
                if mcell.value != new_val:
                    mcell.value = new_val
                    written += 1
    return written


def _read_cell(ws, coord: str):
    try:
        return ws[coord].value
    except Exception:
        return None


def extract_outputs(recalc_wb) -> dict[str, Any]:
    """Pull the headline scalars and result tables out of a recalculated book."""
    out: dict[str, Any] = {"scalars": {}, "tables": {}}

    for key, (sheet, coord) in cellmap.SCALAR_OUTPUTS.items():
        if sheet in recalc_wb.sheetnames:
            out["scalars"][key] = _read_cell(recalc_wb[sheet], coord)
        else:
            out["scalars"][key] = None

    for tname, spec in cellmap.TABLE_OUTPUTS.items():
        sheet = spec["sheet"]
        if sheet not in recalc_wb.sheetnames:
            out["tables"][tname] = []
            continue
        ws = recalc_wb[sheet]
        anchor = column_index_from_string(spec["anchor_col"])
        cols = {name: column_index_from_string(c) for name, c in spec["columns"].items()}
        rows = []
        r = spec["first_row"]
        blanks = 0
        while r <= ws.max_row and blanks < 3:
            if ws.cell(row=r, column=anchor).value in (None, ""):
                blanks += 1
                r += 1
                continue
            blanks = 0
            rows.append({name: ws.cell(row=r, column=ci).value for name, ci in cols.items()})
            r += 1
        out["tables"][tname] = rows
    return out


# Sheets surfaced in the in-app viewer, in display order. The computed result
# tabs first, then the key input tabs for reference.
VIEW_SHEETS: list[str] = [
    "10_Financial_Goals",
    "Retirement Plan",
    "YoY Cash Flow",
    "Insurance Computation",
    "11. Inc Exp,Networth,Rec Invest",
    "2_Income",
    "3_Expenses ",
]


def _fmt_cell(value: Any, number_format: str | None) -> str:
    """Render a recalculated cell value to a display string, honouring the
    Excel number format loosely (percent / thousands / plain)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        nf = number_format or ""
        if "%" in nf:
            return f"{value * 100:.2f}%"
        if "0" in nf and ("," in nf or "#,##" in nf):
            return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}"
        # default: trim floats, keep ints clean
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def render_sheets(recalc_bytes: bytes, sheets: list[str] | None = None) -> list[dict[str, Any]]:
    """Build a grid representation of the recalculated workbook for the in-app
    viewer. Returns a list of {name, rows: [[str, ...], ...]} — one entry per
    sheet, trimmed to its used range. No LibreOffice or desktop app involved:
    the frontend renders these as an HTML grid."""
    wb = openpyxl.load_workbook(io.BytesIO(recalc_bytes), data_only=True)
    want = sheets or VIEW_SHEETS
    out: list[dict[str, Any]] = []
    for name in want:
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        # Trim trailing empty rows/cols.
        max_r, max_c = ws.max_row, ws.max_column
        last_row = 0
        last_col = 0
        for r in range(1, max_r + 1):
            for c in range(1, max_c + 1):
                if ws.cell(r, c).value not in (None, ""):
                    last_row = max(last_row, r)
                    last_col = max(last_col, c)
        if last_row == 0:
            continue
        rows = []
        for r in range(1, last_row + 1):
            row = []
            for c in range(1, last_col + 1):
                cell = ws.cell(r, c)
                row.append(_fmt_cell(cell.value, cell.number_format))
            rows.append(row)
        out.append({"name": name.strip(), "rows": rows})
    return out


def compute_from_upload(
    upload_bytes: bytes, *, master_path: str | None = None, timeout: int = 180
) -> tuple[bytes, dict[str, Any]]:
    """Run the full pipeline on an uploaded firm-template workbook.

    Returns (populated_recalculated_xlsx_bytes, structured_outputs).
    """
    master_path = master_path or MASTER_PATH
    if not os.path.exists(master_path):
        raise FileNotFoundError(
            f"CFP master template missing at {master_path}. Run build_master.py."
        )

    # Load the upload twice: formulas (to detect formula cells) and cached values.
    upload_formulas = openpyxl.load_workbook(io.BytesIO(upload_bytes), data_only=False)
    upload_values = openpyxl.load_workbook(io.BytesIO(upload_bytes), data_only=True)

    # Fresh master copy (formulas intact).
    master_wb = openpyxl.load_workbook(master_path, data_only=False)
    inject_inputs(master_wb, upload_values, upload_formulas)

    work = tempfile.mkdtemp(prefix="cfp_engine_")
    try:
        injected = os.path.join(work, "injected.xlsx")
        master_wb.save(injected)

        recalced_path = recalc_file(injected, timeout=timeout)
        with open(recalced_path, "rb") as fh:
            populated_bytes = fh.read()

        recalc_wb = openpyxl.load_workbook(recalced_path, data_only=True)
        outputs = extract_outputs(recalc_wb)
        # clean up the recalc temp dir
        shutil.rmtree(os.path.dirname(recalced_path), ignore_errors=True)
        return populated_bytes, outputs
    finally:
        shutil.rmtree(work, ignore_errors=True)
