"""Inject the deterministic Tax-regime and Debt-ratio CALCULATIONS into the
working master as native Excel formulas, so LibreOffice — not Python — computes
them. This makes the firm workbook the single source of truth for these numbers
too (the firm's own `Tax Planning` / `Debt Mgt` tabs only carry reference text).

Design rules (mirrors the existing `apply_house_to_nfa` / step-up injectors):
  * Nothing is hard-coded in Python. Statutory constants (slab thresholds, rates,
    deduction caps) are written into AUDITABLE cells on the sheet; the tax/debt
    formulas reference those cells. An advisor can open the workbook, see the
    slab table, and edit it — the recompute follows.
  * Inputs are read from the firm's existing input cells wherever they live at a
    fixed address (gross income, home-loan interest, EMIs, expenses, net worth).
    The only values Python places are the three deduction contributions (80C /
    NPS / 80D) which the firm template captures as free-text rows with no fixed
    address — and even those are only INPUTS; the cap + slab + rebate + cess +
    regime choice are all Excel formulas.

Cell maps for the result cells live in cellmap.SCALAR_OUTPUTS (tax_* / debt_*).
"""

from __future__ import annotations

from typing import Any

TAX_SHEET = "Tax Planning"
DEBT_SHEET = "Debt Mgt"

# Income-tax slabs FY 2025-26 (AY 2026-27). (lower, upper, rate) — mirrors
# stackwealth/skills/tax.py OLD_REGIME_SLABS / NEW_REGIME_SLABS exactly. These
# are written into the sheet as a visible table; the tax formula references them.
_OLD_SLABS = [(0, 250_000, 0.00), (250_000, 500_000, 0.05),
              (500_000, 1_000_000, 0.20), (1_000_000, 1e15, 0.30)]
_NEW_SLABS = [(0, 400_000, 0.00), (400_000, 800_000, 0.05),
              (800_000, 1_200_000, 0.10), (1_200_000, 1_600_000, 0.15),
              (1_600_000, 2_000_000, 0.20), (2_000_000, 2_400_000, 0.25),
              (2_400_000, 1e15, 0.30)]

# Constants (also written to cells, referenced by formula). Mirrors tax.py.
_OLD_STD_DED = 50_000
_NEW_STD_DED = 75_000
_CAP_80C = 150_000
_CAP_80CCD1B = 50_000
_CAP_80D = 75_000          # 25k self + 50k parents
_CAP_24B = 200_000
_OLD_REBATE_THRESHOLD = 500_000
_NEW_REBATE_THRESHOLD = 1_200_000
_CESS_RATE = 0.04
_HOME_LOAN_DEFAULT_RATE = 0.085   # tax.py default when the loan's rate is blank


def _slab_formula(taxable_cell: str, slab_first_row: int, n: int,
                  lower_col: str, upper_col: str, rate_col: str) -> str:
    """Marginal slab tax as a single Excel formula referencing the slab table
    cells (no literals): Σ rate_i * MAX(0, MIN(taxable, upper_i) - lower_i)."""
    terms = []
    for i in range(n):
        r = slab_first_row + i
        terms.append(
            f"{rate_col}{r}*MAX(0,MIN({taxable_cell},{upper_col}{r})-{lower_col}{r})"
        )
    return "=" + "+".join(terms)


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _deduction_inputs(plan) -> tuple[float, float, float]:
    """Raw annual contributions for 80C / 80CCD(1B) / 80D, summed from the plan
    exactly as tax.py does. These are the only values Python supplies — the caps
    and the tax itself are computed by the Excel formulas. Returns (0,0,0) when
    there is no plan (e.g. the golden tests), which the formulas handle."""
    if plan is None:
        return 0.0, 0.0, 0.0
    mi = getattr(plan, "monthly_investments", None)
    ppf = _num(getattr(mi, "ppf", 0)) if mi else 0.0
    rd = _num(getattr(mi, "rd", 0)) if mi else 0.0
    life_prem = _num(getattr(mi, "insurance_premium", 0)) if mi else 0.0
    nps = _num(getattr(mi, "nps", 0)) if mi else 0.0
    contrib_80c = (ppf + rd + life_prem) * 12.0
    contrib_nps = nps * 12.0

    health = 0.0
    ins = getattr(plan, "insurance_details", None)
    if ins:
        hi = getattr(ins, "health_insurance", None)
        ff = getattr(ins, "family_floater", None)
        if hi:
            health += _num(getattr(hi, "annual_premium", 0))
        if ff:
            health += _num(getattr(ff, "annual_premium", 0))
    return contrib_80c, contrib_nps, health


def write_tax_block(wb, plan=None) -> None:
    """Inject the old-vs-new regime tax computation into the Tax Planning sheet
    (free columns I..N). All result cells are mapped in cellmap (tax_*)."""
    if TAX_SHEET not in wb.sheetnames:
        return
    ws = wb[TAX_SHEET]

    # --- slab tables (auditable, referenced by the tax formula) --------------
    # OLD slabs at L..N rows 3.. ; NEW slabs at L..N rows 9.. (kept apart).
    old_first = 3
    for i, (lo, up, rate) in enumerate(_OLD_SLABS):
        r = old_first + i
        ws[f"L{r}"] = lo
        ws[f"M{r}"] = up
        ws[f"N{r}"] = rate
    new_first = old_first + len(_OLD_SLABS) + 1   # one blank row gap
    for i, (lo, up, rate) in enumerate(_NEW_SLABS):
        r = new_first + i
        ws[f"L{r}"] = lo
        ws[f"M{r}"] = up
        ws[f"N{r}"] = rate

    # --- constants -----------------------------------------------------------
    ws["I1"] = "Tax regime computation (FY 2025-26) — engine-injected"
    cells = {
        "J3": _OLD_STD_DED, "J4": _NEW_STD_DED,
        "J5": _CAP_80C, "J6": _CAP_80CCD1B, "J7": _CAP_80D, "J8": _CAP_24B,
        "J9": _OLD_REBATE_THRESHOLD, "J10": _NEW_REBATE_THRESHOLD,
        "J11": _CESS_RATE, "J12": _HOME_LOAN_DEFAULT_RATE,
    }
    for c, v in cells.items():
        ws[c] = v

    # --- inputs --------------------------------------------------------------
    # Gross annual income (year 1). '2_Income'!I6 is the MONTHLY income total
    # (×12 → annual; the firm's net-monthly cell confirms I6 is monthly).
    ws["I15"] = "gross_annual_income"
    ws["J15"] = "='2_Income'!I6*12"
    # Deduction contributions Python supplies (free-text rows have no address).
    c80c, cnps, c80d = _deduction_inputs(plan)
    ws["I16"] = "80C contribution"
    ws["J16"] = c80c
    ws["I17"] = "80CCD(1B) NPS contribution"
    ws["J17"] = cnps
    ws["I18"] = "80D health premium"
    ws["J18"] = c80d
    # Home-loan interest p.a. from the loan tab (outstanding * rate, default rate
    # when the sheet's rate cell is blank) — pure Excel, no Python.
    ws["I19"] = "home loan interest p.a."
    ws["J19"] = (
        "=IFERROR('8_Loans_Liabilities'!C2*"
        "IF(N('8_Loans_Liabilities'!E2)>0,'8_Loans_Liabilities'!E2,J12),0)"
    )

    # --- capped deductions (Excel applies the caps) --------------------------
    ws["I21"] = "80C (capped)";      ws["J21"] = "=MIN(J5,J16)"
    ws["I22"] = "80CCD1B (capped)";  ws["J22"] = "=MIN(J6,J17)"
    ws["I23"] = "80D (capped)";      ws["J23"] = "=MIN(J7,J18)"
    ws["I24"] = "24b (capped)";      ws["J24"] = "=MIN(J8,J19)"
    ws["I25"] = "HRA";               ws["J25"] = 0
    ws["I26"] = "deductions total";  ws["J26"] = "=J21+J22+J23+J24+J25"

    # --- OLD regime ----------------------------------------------------------
    ws["I28"] = "old taxable";        ws["J28"] = "=MAX(0,J15-J3-J26)"
    ws["I29"] = "old tax (slabs)"
    ws["J29"] = _slab_formula("J28", old_first, len(_OLD_SLABS), "L", "M", "N")
    ws["I30"] = "old after 87A";      ws["J30"] = "=IF(J28<=J9,0,J29)"
    ws["I31"] = "old cess";           ws["J31"] = "=J30*J11"
    ws["I32"] = "old total tax";      ws["J32"] = "=J30+J31"
    ws["I33"] = "old effective rate"; ws["J33"] = "=IF(J15>0,J32/J15,0)"

    # --- NEW regime ----------------------------------------------------------
    ws["I35"] = "new taxable";        ws["J35"] = "=MAX(0,J15-J4)"
    ws["I36"] = "new tax (slabs)"
    ws["J36"] = _slab_formula("J35", new_first, len(_NEW_SLABS), "L", "M", "N")
    ws["I37"] = "new after 87A";      ws["J37"] = "=IF(J35<=J10,0,J36)"
    ws["I38"] = "new cess";           ws["J38"] = "=J37*J11"
    ws["I39"] = "new total tax";      ws["J39"] = "=J37+J38"
    ws["I40"] = "new effective rate"; ws["J40"] = "=IF(J15>0,J39/J15,0)"

    # --- recommendation ------------------------------------------------------
    ws["I42"] = "recommended regime"; ws["J42"] = '=IF(J39<=J32,"new","old")'
    ws["I43"] = "annual savings";     ws["J43"] = "=ABS(J39-J32)"


def write_debt_block(wb, plan=None) -> None:
    """Inject the debt-adequacy ratios (DSCR / DTI / DNI) into the Debt Mgt sheet
    (free columns H..K) as Excel formulas referencing the income / loan / net-
    worth cells. Mirrors stackwealth/skills/debt.py compute_debt_ratios.

    Ratios resolve to -1 when their denominator is 0 (no EMI / income / assets);
    the Python mapping reads -1 back as None, matching debt.py's None."""
    if DEBT_SHEET not in wb.sheetnames:
        return
    ws = wb[DEBT_SHEET]
    ws["H1"] = "Debt adequacy ratios — engine-injected"
    # '2_Income'!I6 is MONTHLY income (×12 → annual); Retirement Plan E17 is
    # already annual; loan EMIs (D column) are monthly (×12 → annual).
    ws["H2"] = "annual income";   ws["I2"] = "='2_Income'!I6*12"
    ws["H3"] = "annual expenses"; ws["I3"] = "='Retirement Plan'!E17"
    ws["H4"] = "annual EMI";      ws["I4"] = "=SUM('8_Loans_Liabilities'!D2:D9)*12"
    ws["H5"] = "total debt";      ws["I5"] = "='8_Loans_Liabilities'!C10"
    ws["H6"] = "total assets";    ws["I6"] = "='11. Inc Exp,Networth,Rec Invest'!I49"
    ws["H7"] = "income for debt service"; ws["I7"] = "=I2-I3"
    # Ratios resolve to a BLANK cell when their denominator is 0 (no EMI /
    # income / assets) → the Python mapping reads blank as None, matching
    # debt.py. A blank can't collide with a real ratio (which may be negative
    # when expenses exceed income), unlike a numeric sentinel.
    # DSCR = (income - expenses) / annual EMI
    ws["H8"] = "DSCR"; ws["I8"] = '=IF(I4>0,I7/I4,"")'
    # DTI = total debt / annual income
    ws["H9"] = "DTI"; ws["I9"] = '=IF(I2>0,I5/I2,"")'
    # DNI = total debt / total assets
    ws["H10"] = "DNI"; ws["I10"] = '=IF(I6>0,I5/I6,"")'


def write_calc_blocks(wb, plan=None) -> None:
    """Inject both calculation blocks. Safe to call on every compute path."""
    write_tax_block(wb, plan)
    write_debt_block(wb, plan)
