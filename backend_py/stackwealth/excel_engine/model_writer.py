"""Write a PlanState into the firm master template's input cells.

This is what makes the Excel engine *format-agnostic*. Direct cell-injection
(``engine.compute_from_upload``) only works when the upload is the firm's
standard template. For any other layout (e.g. the "Financial Planning_Client"
format with renamed tabs and a different cell structure), the LLM intake first
normalises it into a ``PlanState``; this module then writes that structured data
into the master's known input cells, and LibreOffice recalculates exactly as it
would for a native firm-template upload.

Only fields that drive the firm model are written. Missing fields are skipped
(the master's input cells were pre-cleared by build_master, so anything not
written stays blank).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Base year the master's YoY anchor uses (the year seed on the YoY tab is kept
# from the template). Ages on 1_Personal_Details are computed as (D3 - DOB), so
# we anchor D3 to this base year for a consistent projection start.
BASE_YEAR = 2026
BASE_DATE = datetime(BASE_YEAR, 6, 1)


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _to_date(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v.strip():
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(v.strip()[:10], fmt)
            except ValueError:
                continue
    return None


def _set(ws, coord: str, value: Any) -> None:
    if value is None:
        return
    ws[coord] = value


def _set_salary_horizon(ws_yoy, base_age: float | None, retire_age: float | None) -> None:
    """Make the YoY salary column (E) stop at the client's actual retirement age.

    The firm template hardcodes salary to grow for exactly 20 rows (Y0–Y20, the
    sample client's working life) and is blank after — so every client's salary
    otherwise stops at ~age 56 regardless of their retirement age. We re-shape
    column E to the real horizon: a growth formula through the retirement year,
    blank afterwards (business income / other columns are untouched)."""
    if base_age is None or retire_age is None:
        return
    FIRST, LAST = 6, 60  # YoY data rows
    retire_row = FIRST + max(0, round(retire_age - base_age))
    for r in range(FIRST + 1, LAST + 1):
        if r <= retire_row:
            # working year → ensure the salary growth formula is present
            cur = ws_yoy[f"E{r}"].value
            if not (isinstance(cur, str) and cur.startswith("=")):
                ws_yoy[f"E{r}"] = f"=E{r - 1}*(1+E$5)"
        else:
            # retired → no salary
            ws_yoy[f"E{r}"] = None


def write_plan_to_master(master_wb, plan) -> int:
    """Populate ``master_wb`` (a fresh master copy) from ``plan``. Returns the
    number of cells written. Formula cells are left untouched."""
    written = 0

    def setc(ws, coord, value):
        nonlocal written
        if value is None:
            return
        ws[coord] = value
        written += 1

    # ── 1_Personal_Details ────────────────────────────────────────────────
    pd = plan.personal_details
    persons = (plan.assumptions.persons if plan.assumptions else None) or []
    p_self = persons[0] if len(persons) > 0 else None
    p_spouse = persons[1] if len(persons) > 1 else None
    ws = master_wb["1_Personal_Details"]
    setc(ws, "E2", BASE_YEAR)
    setc(ws, "D3", BASE_DATE)
    # Client
    dob = _to_date(getattr(pd, "date_of_birth", None)) or (
        _to_date(getattr(p_self, "date_of_birth", None)) if p_self else None
    )
    setc(ws, "C5", dob)
    retire = (
        _num(getattr(pd, "retirement_age_target", None))
        or (_num(getattr(p_self, "retirement_age", None)) if p_self else None)
        or 60
    )
    setc(ws, "H5", retire)
    setc(ws, "I5", (_num(getattr(p_self, "life_expectancy", None)) if p_self else None) or 85)
    # Spouse. The firm's retirement model derives the post-retirement horizon
    # from the SPOUSE's lifetime (provides until the dependent spouse passes).
    # For a single client, leaving the spouse cells blank yields a negative
    # horizon and a garbage corpus — so mirror the client into the spouse cells
    # (horizon = the client's own lifetime).
    spouse_life = _num(getattr(p_spouse, "life_expectancy", None)) if p_spouse else None
    spouse_dob = _to_date(getattr(p_spouse, "date_of_birth", None)) if p_spouse else None
    is_married = str(getattr(pd, "marital_status", "") or "").lower().startswith("married")
    if p_spouse and (spouse_dob or spouse_life) and is_married:
        setc(ws, "C6", spouse_dob or dob)
        setc(ws, "H6", _num(getattr(p_spouse, "retirement_age", None)) or retire)
        setc(ws, "I6", spouse_life or 85)
    else:
        # Single client → mirror self so the horizon is the client's lifetime.
        setc(ws, "C6", dob)
        setc(ws, "H6", retire)
        setc(ws, "I6", (_num(getattr(p_self, "life_expectancy", None)) if p_self else None) or 85)

    # ── 2_Income (rows 6-9: salary/business/rental/other; F=client G=spouse) ─
    inc = plan.income_details
    if inc:
        ws = master_wb["2_Income"]
        setc(ws, "F6", _num(inc.client_salary_in_hand))
        setc(ws, "G6", _num(inc.spouse_salary_in_hand))
        setc(ws, "F7", _num(inc.client_business_income))
        setc(ws, "G7", _num(inc.spouse_business_income))
        setc(ws, "F8", _num(inc.client_rental_income))
        setc(ws, "G8", _num(inc.spouse_rental_income))
        setc(ws, "F9", _num(inc.client_other_income))
        setc(ws, "G9", _num(inc.spouse_other_income))

    # Salary in the YoY must stop at the client's actual retirement age, not the
    # template's frozen 20-year horizon.
    base_age = (BASE_DATE - dob).days / 365.25 if dob else None
    _set_salary_horizon(master_wb["YoY Cash Flow"], base_age, retire)

    # ── 3_Expenses (value in col H, total I; map model fields to firm rows) ──
    exp = plan.monthly_expenses
    if exp:
        ws = master_wb["3_Expenses "]
        # Firm rows: 6 Rent, 7 Living, 8 Children (excluded post-retirement),
        # 9 Transport, 10 Utilities, 11 Other, 12 Lifestyle, 13 Medical/Insurance.
        setc(ws, "H6", _num(exp.rent_or_emi))
        setc(ws, "H7", (_num(exp.household_expenses) or 0) + (_num(exp.groceries) or 0) or None)
        setc(ws, "H8", _num(exp.school_fees))          # children → row 8 (post-retire excl.)
        setc(ws, "H10", _num(exp.utilities))
        setc(ws, "H12", _num(exp.travel_or_lifestyle))
        setc(ws, "H13", (_num(exp.medical) or 0) + (_num(exp.insurance_premium) or 0) or None)
        setc(ws, "H11", _num(exp.other_emis))

    # ── 5_Recurring_Investments (col C monthly amount, rows 2-7) ────────────
    mi = plan.monthly_investments
    if mi:
        ws = master_wb["5_Recurring_Investments"]
        setc(ws, "C2", _num(mi.mutual_fund_sip))
        setc(ws, "C3", _num(mi.nps))
        setc(ws, "C4", _num(mi.ppf))
        setc(ws, "C5", _num(mi.rd))
        setc(ws, "C6", _num(mi.direct_equity))
        setc(ws, "C12", _num(mi.insurance_premium))

    # ── 4A_Mutual_Funds (B name, H value, I SIP) ───────────────────────────
    ws = master_wb["4A_Mutual_Funds"]
    for i, h in enumerate(plan.mutual_funds or []):
        r = 2 + i
        if r > 9:
            break
        setc(ws, f"B{r}", getattr(h, "fund_name", None))
        setc(ws, f"H{r}", _num(getattr(h, "current_value", None)))
        setc(ws, f"I{r}", _num(getattr(h, "sip_amount", None)))

    # ── 4B_Equity_Stocks (B name, E current value) ─────────────────────────
    ws = master_wb["4B_Equity_Stocks"]
    for i, h in enumerate(plan.equity_stocks or []):
        r = 2 + i
        if r > 25:
            break
        setc(ws, f"B{r}", getattr(h, "stock_name", None))
        setc(ws, f"E{r}", _num(getattr(h, "current_value", None)))

    # ── 4C_Fixed_Income (C name, D invested, E current value) ──────────────
    ws = master_wb["4C_Fixed_Income"]
    for i, h in enumerate(plan.fixed_income or []):
        r = 2 + i
        if r > 8:
            break
        setc(ws, f"C{r}", getattr(h, "instrument", None))
        setc(ws, f"D{r}", _num(getattr(h, "invested_amount", None)))
        setc(ws, f"E{r}", _num(getattr(h, "current_value", None)))

    # ── 4D_Real_Estate (C market value, D loan, E rental) ──────────────────
    ws = master_wb["4D_Real_Estate"]
    for i, h in enumerate(plan.real_estate or []):
        r = 2 + i
        if r > 8:
            break
        setc(ws, f"C{r}", _num(getattr(h, "current_value", None)))

    # ── 4E_Gold & Others (C current value) ─────────────────────────────────
    ws = master_wb["4E_Gold & Others"]
    for i, h in enumerate(plan.gold or []):
        r = 2 + i
        if r > 8:
            break
        setc(ws, f"C{r}", _num(getattr(h, "current_value", None)))

    # ── 6_Liquid_Capital (C amount) ────────────────────────────────────────
    lc = plan.liquid_capital
    if lc:
        ws = master_wb["6_Liquid_Capital"]
        setc(ws, "C2", _num(lc.savings_account_balance))
        setc(ws, "C3", _num(lc.idle_cash_for_investment))
        setc(ws, "C4", _num(lc.fd_breakable_for_investment))

    # ── 7_Emergency_Fund (C3 total corpus) ─────────────────────────────────
    ef = plan.emergency_fund
    if ef:
        ws = master_wb["7_Emergency_Fund"]
        setc(ws, "C3", _num(ef.total_emergency_corpus) or _num(ef.emergency_fund_available))

    # ── 8_Loans_Liabilities (C outstanding, D EMI, E rate) ─────────────────
    li = plan.loans_liabilities
    if li:
        ws = master_wb["8_Loans_Liabilities"]
        rows = {"home_loan": 2, "car_loan": 3, "personal_loan": 4, "credit_card_dues": 5}
        for name, r in rows.items():
            blk = getattr(li, name, None)
            if blk is None:
                continue
            setc(ws, f"C{r}", _num(getattr(blk, "outstanding_amount", None)))
            setc(ws, f"D{r}", _num(getattr(blk, "emi", None)))
            setc(ws, f"E{r}", _num(getattr(blk, "interest_rate", None)))

    # ── 9_Insurance_Details (E cover, F premium) ───────────────────────────
    ins = plan.insurance_details
    if ins:
        ws = master_wb["9_Insurance_Details"]
        term = getattr(ins, "term_plan", None)
        if term:
            setc(ws, "E2", _num(getattr(term, "cover_amount", None)))
            setc(ws, "F2", _num(getattr(term, "annual_premium", None)))
        health = getattr(ins, "health_insurance", None) or getattr(ins, "family_floater", None)
        if health:
            setc(ws, "E5", _num(getattr(health, "cover_amount", None)))
            setc(ws, "F5", _num(getattr(health, "annual_premium", None)))

    # ── 10_Financial_Goals (A name, C target year, E today's cost, F nature) ─
    # The master's E column is "Today's Cost" and the workbook inflates it to a
    # future value. So when the model only carries a FUTURE target (e.g. a file
    # whose goal column is "Future Value Needed"), discount it back to today's
    # money first — otherwise the workbook double-counts inflation.
    ws = master_wb["10_Financial_Goals"]
    NATURE = {"one_time": "One Time", "annual": "Annual", "recurring": "Annual"}
    for i, g in enumerate(plan.financial_goals or []):
        r = 3 + i
        if r > 17:
            break
        year = _num(getattr(g, "target_year", None))
        today = _num(getattr(g, "today_cost", None))
        target = _num(getattr(g, "target_amount", None))
        if today is None and target is not None:
            in_today = getattr(g, "is_target_in_today_money", True)
            if in_today is False and year and year > BASE_YEAR:
                infl = _num(getattr(g, "inflation_assumed", None)) or 0.07
                today = target / ((1 + infl) ** (int(year) - BASE_YEAR))
            else:
                today = target
        setc(ws, f"A{r}", getattr(g, "goal_name", None))
        setc(ws, f"C{r}", year)
        # Years-to-go (D) is an array formula in the firm template that we clear;
        # write it explicitly so the workbook inflates today's cost → future value.
        if year and year >= BASE_YEAR:
            setc(ws, f"D{r}", int(year) - BASE_YEAR)
        setc(ws, f"E{r}", round(today) if today is not None else None)
        freq = (getattr(g, "contribution_frequency", None) or "").lower()
        setc(ws, f"F{r}", NATURE.get(freq, "One Time"))

    return written
