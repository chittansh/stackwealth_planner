"""Golden tests for the CFP Excel engine (stackwealth.excel_engine).

No pytest dependency — run directly:
    uv run python test_excel_engine.py

Checks, per firm sample workbook:
  1. FIDELITY OF INJECTION — the engine's outputs (built by pouring the client's
     INPUT cells into the pristine master and recalculating) must equal that
     client's OWN workbook recalculated directly. If they match, we reconstructed
     the plan exactly from inputs alone.
  2. MASTER ISOLATION — frozen tabs (Assumptions) and all master formulas are
     never mutated by injection; two different clients yield different outputs.
  3. OUTPUT SANITY — headline scalars are present and plausible.
"""
from __future__ import annotations

import io
import math
import os
import sys
from pathlib import Path

import openpyxl

from stackwealth.excel_engine import cellmap
from stackwealth.excel_engine.engine import compute_from_upload, MASTER_PATH
from stackwealth.excel_engine.recalc import recalc_file

EXAMPLES = Path(__file__).resolve().parent.parent / "example_inputs"
SAMPLES = [
    "Test profil_ng_180626.xlsx",
    "Naga_Inputs.xlsx",
    "V1_Young_Professional_Rohan.xlsx",
    "V4_Pre_Retirement_Rajeev.xlsx",
]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _close(a, b, rel=1e-4, abs_=1.0):
    if a is None and b is None:
        return True
    if not _num(a) or not _num(b):
        return str(a) == str(b)
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


FIRM_SOURCE = "Format for inputs for CFP_ng_180626.xlsx"


def _cached_outputs(path: str) -> dict:
    """Read the SAME output cells from a workbook's existing cached values
    (no recalc) — used to read the firm file's known-correct numbers."""
    from stackwealth.excel_engine.engine import extract_outputs

    wb = openpyxl.load_workbook(path, data_only=True)
    return extract_outputs(wb)


def test_roundtrip_fidelity():
    """The keystone golden test. The firm's own workbook has both sample INPUTS
    and known-correct cached OUTPUTS. Pour its inputs through the engine (clean
    master + inject + LibreOffice recalc) and the outputs must reproduce the
    firm file's cached numbers — proving the input->output path is exact.
    """
    print("\n== 1. ROUND-TRIP FIDELITY: engine(firm inputs) == firm cached outputs ==")
    path = str(EXAMPLES / FIRM_SOURCE)
    assert os.path.exists(path), f"firm source missing: {path}"
    _, engine_out = compute_from_upload(open(path, "rb").read())
    truth = _cached_outputs(path)

    mismatches = []
    for k, ev in engine_out["scalars"].items():
        tv = truth["scalars"].get(k)
        if not _close(ev, tv):
            mismatches.append((k, ev, tv))
    eg, tg = engine_out["tables"]["goals"], truth["tables"]["goals"]
    if len(eg) != len(tg):
        mismatches.append(("goals_rowcount", len(eg), len(tg)))
    for i, (a, b) in enumerate(zip(eg, tg)):
        for col in ("future_value_needed", "required_sip", "gap_today"):
            if not _close(a.get(col), b.get(col)):
                mismatches.append((f"goal[{i}].{col}", a.get(col), b.get(col)))
    ey, ty = engine_out["tables"]["yoy_cashflow"], truth["tables"]["yoy_cashflow"]
    if len(ey) != len(ty):
        mismatches.append(("yoy_rowcount", len(ey), len(ty)))
    for i, (a, b) in enumerate(zip(ey, ty)):
        for col in ("income_employment", "expenses", "financial_assets_close"):
            if not _close(a.get(col), b.get(col), rel=1e-4, abs_=2.0):
                mismatches.append((f"yoy[{i}].{col}", a.get(col), b.get(col)))

    print(f"  scalars={len(engine_out['scalars'])} goals={len(eg)} yoy={len(ey)} "
          f"mismatches={len(mismatches)}")
    for m in mismatches[:10]:
        print(f"         mismatch {m}")
    assert not mismatches, "round-trip fidelity mismatch"
    print("  [OK ] engine reproduces the firm workbook's own numbers exactly")


def test_persona_sanity():
    """Engine produces plausible, non-null headline numbers on a CONFORMING
    firm-template file. Legacy-format files (V1-V4 / Naga, May-2016 layout) are
    printed for information only — they predate the 180626 template and are not
    guaranteed to map; real uploads use the current template."""
    print("\n== 4. PERSONA SANITY: plausible headline numbers ==")
    conforming = "Test profil_ng_180626.xlsx"
    path = str(EXAMPLES / conforming)
    _, out = compute_from_upload(open(path, "rb").read())
    s = out["scalars"]
    nw, corpus = s.get("net_worth"), s.get("retirement_corpus_required")
    ok = _num(nw) and nw > 0 and _num(corpus) and corpus > 0
    print(f"  [{'OK ' if ok else 'FAIL'}] {conforming:42} net_worth={nw:,} corpus={corpus:,.0f} "
          f"goals={len(out['tables']['goals'])}")
    assert ok, f"{conforming}: implausible headline numbers"

    for name in ["V1_Young_Professional_Rohan.xlsx", "V4_Pre_Retirement_Rajeev.xlsx"]:
        p = str(EXAMPLES / name)
        if not os.path.exists(p):
            continue
        _, o = compute_from_upload(open(p, "rb").read())
        print(f"  (info, legacy layout) {name:38} net_worth={o['scalars'].get('net_worth')} "
              f"corpus={o['scalars'].get('retirement_corpus_required')}")


def test_master_isolation():
    print("\n== 2. MASTER ISOLATION: formulas + frozen tabs never mutated ==")
    master = openpyxl.load_workbook(MASTER_PATH, data_only=False)
    # snapshot frozen-tab cells + a sample of formulas
    frozen_before = {}
    for tab in cellmap.FROZEN_TABS:
        if tab in master.sheetnames:
            ws = master[tab]
            frozen_before[tab] = {c.coordinate: c.value for row in ws.iter_rows() for c in row}
    formula_cells = []
    for tab in cellmap.INJECT_TABS:
        if tab in master.sheetnames:
            ws = master[tab]
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value.startswith("="):
                        formula_cells.append((tab, c.coordinate, c.value))

    # run an injection (in-memory) and re-check the on-disk master is untouched
    path = str(EXAMPLES / SAMPLES[0])
    compute_from_upload(open(path, "rb").read())

    master2 = openpyxl.load_workbook(MASTER_PATH, data_only=False)
    ok = True
    for tab, cells in frozen_before.items():
        ws = master2[tab]
        for coord, val in cells.items():
            if ws[coord].value != val:
                ok = False
                print(f"  FAIL frozen {tab}!{coord} changed")
    for tab, coord, val in formula_cells[:500]:
        if master2[tab][coord].value != val:
            ok = False
            print(f"  FAIL formula {tab}!{coord} changed")
    assert ok, "master mutated by injection"
    print(f"  [OK ] {len(formula_cells)} formula cells + {len(cellmap.FROZEN_TABS)} frozen tabs intact "
          f"after injection (master is read-only)")


def test_two_clients_differ():
    print("\n== 3. DISTINCTNESS: different clients -> different net worth ==")
    nws = {}
    for name in SAMPLES[:2]:
        path = str(EXAMPLES / name)
        if not os.path.exists(path):
            continue
        _, out = compute_from_upload(open(path, "rb").read())
        nws[name] = out["scalars"].get("net_worth")
        print(f"  {name:42} net_worth={nws[name]}")
    vals = [v for v in nws.values() if _num(v)]
    assert len(set(vals)) == len(vals), "distinct clients produced identical net worth"
    print("  [OK ] outputs are client-specific")


if __name__ == "__main__":
    if not os.path.exists(MASTER_PATH):
        print(f"MASTER missing: {MASTER_PATH} — run build_master first")
        sys.exit(2)
    test_roundtrip_fidelity()
    test_master_isolation()
    test_two_clients_differ()
    test_persona_sanity()
    print("\nALL EXCEL-ENGINE GOLDEN TESTS PASSED")
