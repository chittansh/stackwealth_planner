"""Generate the pristine CFP master template shipped with the app.

Takes the firm's source workbook and clears the SAMPLE client's data from the
input cells (every non-formula cell on the INJECT tabs) while preserving all
formulas and all frozen-tab assumptions. The result is committed as
``master/cfp_master.xlsx`` and is what the engine injects fresh client data into.

Run once whenever the firm ships a new template:
    uv run python -m stackwealth.excel_engine.build_master <source.xlsx>
"""

from __future__ import annotations

import os
import sys

import openpyxl

from . import cellmap

_HERE = os.path.dirname(__file__)
OUT_PATH = os.path.join(_HERE, "master", "cfp_master.xlsx")

# Header/label rows & columns to KEEP when clearing an input tab. Labels are
# identical between master and upload, so keeping them is harmless and makes the
# blank template human-readable. We clear only data-bearing cells: anything
# numeric, or text below the header band. Headers live in the first two rows or
# the first column of each tab in this template.
def _looks_like_label(coord_row: int, coord_col: int, value) -> bool:
    if not isinstance(value, str):
        return False
    # keep header band (rows 1-2) and the left label column (A) text
    return coord_row <= 2 or coord_col == 1


def build(source: str) -> str:
    wb = openpyxl.load_workbook(source, data_only=False)
    cleared = 0
    for tab in cellmap.INJECT_TABS:
        if tab not in wb.sheetnames:
            continue
        ws = wb[tab]
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if v is None:
                    continue
                if isinstance(v, str) and v.startswith("="):
                    continue  # keep formulas
                if _looks_like_label(c.row, c.column, v):
                    continue  # keep header / label text
                c.value = None
                cleared += 1
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    wb.save(OUT_PATH)
    print(f"Cleared {cleared} sample-data cells across {len(cellmap.INJECT_TABS)} input tabs")
    print(f"Master written -> {OUT_PATH}")
    return OUT_PATH


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m stackwealth.excel_engine.build_master <source.xlsx>")
        raise SystemExit(2)
    build(sys.argv[1])
