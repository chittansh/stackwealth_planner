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
import io

import openpyxl

from ..excel_engine.engine import compute_from_plan, compute_from_upload
from ..logging_config import get_logger
from ..types import CashFlowRow, NetWorthSeriesPoint

_log = get_logger(__name__)


class NoWorkbookError(RuntimeError):
    """Raised when a household has no stored firm-template upload to compute."""


def _is_firm_template(source: bytes) -> bool:
    """Detect the firm's native input template by its signature tab names.
    Alternate formats (e.g. 'Financial Planning_Client …' with '2_Income_Details'
    / '5_Monthly_Investments') don't have these and go through the model-writer."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(source), read_only=True)
        names = set(wb.sheetnames)
        wb.close()
        return "2_Income" in names and "5_Recurring_Investments" in names
    except Exception:
        return False


def _f(v: Any) -> float:
    """Coerce an Excel cell to float; blanks / errors / text → 0."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _excel_goal_blocks(outputs: dict[str, Any], plan) -> list[dict]:
    """Map the firm workbook's ``10_Financial_Goals`` rows into the goal-block
    shape the canvas GoalsView reads (``plan.computed.cfp.goal_blocks``).

    Every number — future value, required/existing SIP, gap, post-tax ROI —
    comes straight from the recalculated sheet, so the "Excel-faithful" goal
    cards show exactly what the Computed-Excel tab shows. We deliberately omit
    the per-goal affordability fields (incremental / affordable SIP): the firm
    sheet doesn't ration a goal's SIP against household surplus, so faking those
    would make the UI assert an affordability check we didn't run.
    """
    rows = (outputs.get("tables") or {}).get("goals") or []
    # Resolve each Excel goal name back to a PlanState goal id so the FE can
    # match a block to its goal (it falls back to a name match when id is None).
    id_by_name: dict[str, Any] = {}
    for g in (getattr(plan, "financial_goals", None) or []):
        nm = (getattr(g, "goal_name", None) or "").strip().lower()
        if nm:
            id_by_name.setdefault(nm, getattr(g, "id", None))

    blocks: list[dict] = []
    for r in rows:
        name = r.get("goal")
        if not isinstance(name, str) or not name.strip():
            continue
        # Retirement is rendered from cfp.retirement (its own corpus engine),
        # not as a regular goal row — skip it here to avoid a duplicate card.
        if "retire" in name.lower():
            continue
        # Skip the template's blank placeholder rows (a named row the client
        # never filled in — no cost and no future value), which would otherwise
        # render as an empty goal card.
        today_cost = _f(r.get("todays_cost"))
        future_value = _f(r.get("future_value_needed"))
        if today_cost <= 0 and future_value <= 0:
            continue
        required = _f(r.get("required_sip"))
        existing = _f(r.get("existing_sip"))
        # The "already running" column can be blank on the sheet; back it out of
        # required − remaining so the Existing-SIP cell still reconciles.
        if existing == 0 and required:
            existing = max(0.0, required - _f(r.get("sip_shortfall")))
        blocks.append({
            "goal_name": name.strip(),
            "goal_id": id_by_name.get(name.strip().lower()),
            "target_year": int(_f(r.get("target_year"))) or None,
            "years_to_go": int(round(_f(r.get("years_to_go")))) or None,
            "today_cost": today_cost,
            "inflation_used": _f(r.get("inflation")),
            "future_value_needed": future_value,
            "allocated_today_total": _f(r.get("current_allocated")),
            "gap_today": _f(r.get("gap_today")),
            "fv_gap": _f(r.get("future_value_of_gap")),
            "effective_return": _f(r.get("effective_return")),
            "required_sip_monthly": required,
            "existing_sip_monthly": existing,
        })
    return blocks


def _excel_insurance(scal: dict[str, Any]) -> dict:
    """Map the workbook's Insurance Computation scalars into the InsuranceView
    shape (``plan.computed.cfp.insurance``). Empty when the sheet had no cover
    figures (e.g. a plan with no dependants), so the FE keeps its estimate."""
    hlv = _f(scal.get("human_life_value"))
    life_required = _f(scal.get("life_cover_required"))
    life_existing = _f(scal.get("life_cover_existing"))
    life_additional = _f(scal.get("life_cover_additional"))
    health_required = _f(scal.get("health_cover_required"))
    health_existing = _f(scal.get("health_cover_existing"))
    health_additional = _f(scal.get("health_cover_additional"))
    if not (life_required or health_required or hlv):
        return {}
    return {
        "human_life_value": hlv,
        "total_need_including_loans": life_required,
        "existing_cover": life_existing,
        # F38 (additional) already nets disposable assets against the need; back
        # those assets out so the FE's covered-vs-need bar reconciles.
        "investable_assets": max(0.0, life_required - life_existing - life_additional),
        "additional_cover_required": life_additional,
        "health": {
            "required": health_required,
            "existing_cover": health_existing,
            "additional_cover_required": health_additional,
        },
    }


def _excel_retirement(scal: dict[str, Any]) -> dict:
    """Map the Retirement Plan scalars into the retirement-block shape the
    GoalsView retirement card reads. The 3-case glide (RetirementGlideView's
    ``cases``) is a Python construct the firm sheet doesn't expose, so it is
    left to the Python layer; here we only supply the authoritative headline
    corpus + SIPs and a funded-% derived from ongoing-vs-required SIP."""
    corpus = _f(scal.get("retirement_corpus_required"))
    if corpus <= 0:
        return {}
    gross = _f(scal.get("retirement_gross_monthly_sip"))
    ongoing = _f(scal.get("retirement_ongoing_monthly_sip"))
    out = {
        "corpus_required": corpus,
        "years_to_retire": _f(scal.get("years_to_retire")),
        "retirement_annual_expense_today": _f(scal.get("annual_expense_today")),
        "gross_monthly_sip": gross,
        "ongoing_retirement_sip_monthly": ongoing,
    }
    if gross > 0:
        out["stepup_funded_pct"] = min(100.0, max(0.0, ongoing / gross * 100.0))
    return out


def _excel_tax_regime(scal: dict[str, Any]) -> dict:
    """Map the engine-injected Tax-regime block into the cfp.tax_regime shape
    (old-vs-new comparison). Every number is computed by the Excel formulas in
    model_calcs — Python only labels the result. Empty when the workbook had no
    income to tax."""
    gross = _f(scal.get("tax_gross_income"))
    if gross <= 0:
        return {}
    old_total = round(_f(scal.get("tax_old_total")))
    new_total = round(_f(scal.get("tax_new_total")))
    recommended = scal.get("tax_recommended_regime")
    if recommended not in ("old", "new"):
        recommended = "new" if new_total <= old_total else "old"
    savings = round(_f(scal.get("tax_annual_savings")))
    if recommended == "old":
        rationale = f"Old regime saves ₹{savings:,} via 80C/80D/24(b) deductions"
    else:
        rationale = (
            f"New regime saves ₹{savings:,} — current deductions don't outweigh "
            "the wider slabs"
        )
    return {
        "fy": "2025-26",
        "annual_gross_income": round(gross),
        "old_regime": {
            "standard_deduction": 50_000,
            "deductions": {
                "80C": round(_f(scal.get("tax_ded_80c"))),
                "80CCD_1B": round(_f(scal.get("tax_ded_80ccd1b"))),
                "80D": round(_f(scal.get("tax_ded_80d"))),
                "24b": round(_f(scal.get("tax_ded_24b"))),
                "HRA": round(_f(scal.get("tax_ded_hra"))),
                "total": round(_f(scal.get("tax_ded_total"))),
            },
            "taxable_income": round(_f(scal.get("tax_old_taxable"))),
            "tax_before_cess": round(_f(scal.get("tax_old_before_cess"))),
            "cess": round(_f(scal.get("tax_old_cess"))),
            "total_tax": old_total,
            "effective_rate": round(_f(scal.get("tax_old_effective_rate")), 4),
        },
        "new_regime": {
            "standard_deduction": 75_000,
            "taxable_income": round(_f(scal.get("tax_new_taxable"))),
            "tax_before_cess": round(_f(scal.get("tax_new_before_cess"))),
            "cess": round(_f(scal.get("tax_new_cess"))),
            "total_tax": new_total,
            "effective_rate": round(_f(scal.get("tax_new_effective_rate")), 4),
        },
        "recommended_regime": recommended,
        "annual_savings_with_recommended": savings,
        "rationale": rationale,
    }


# Debt-ratio judgement bands (presentational labels derived from the Excel
# ratio — the ratio itself is computed in the workbook). Mirrors debt.py.
_DEBT_DEFAULT_RATES_PCT = {
    "home_loan": 8.5, "car_loan": 9.5, "personal_loan": 12.0, "credit_card_dues": 24.0,
}
_DEBT_LABELS = {
    "home_loan": "Home Loan", "car_loan": "Car Loan",
    "personal_loan": "Personal Loan", "credit_card_dues": "Credit Card",
}


def _dscr_status(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return "healthy" if x >= 1.25 else "watch" if x >= 1.0 else "reduce debt"


def _dti_status(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return "healthy" if x <= 0.35 else "watch" if x <= 0.50 else "high"


def _dni_status(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return "healthy" if x <= 0.20 else "watch" if x <= 0.30 else "high"


def _excel_debt(scal: dict[str, Any], plan) -> dict:
    """Map the engine-injected Debt block into cfp.debt (ratios + repayment
    strategies). The ratios are Excel formulas (DSCR/DTI/DNI); a blank cell
    means an undefined denominator → None (a real ratio may be negative when
    expenses exceed income, so only blanks — not negatives — map to None). The
    repayment ORDERING is a sequence (not a financial calc) built from the
    plan's loans, mirroring debt.py."""
    def _ratio(key: str) -> Optional[float]:
        v = scal.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        return round(float(v), 3)

    total_debt = _f(scal.get("debt_total_outstanding"))
    if total_debt <= 0 and not (getattr(plan, "loans_liabilities", None)):
        return {}

    dscr, dti, dni = _ratio("debt_dscr"), _ratio("debt_dti"), _ratio("debt_dni")

    # Build the loan rows from the plan (labels + outstanding + rate) for the
    # avalanche/snowball/blizzard ORDER — sequencing, not money math.
    rows: list[dict] = []
    loans = getattr(plan, "loans_liabilities", None)
    if loans:
        for kind in ("home_loan", "car_loan", "personal_loan", "credit_card_dues"):
            blk = getattr(loans, kind, None)
            if not blk:
                continue
            out = _f(getattr(blk, "outstanding_amount", 0))
            if out <= 0:
                continue
            rate = getattr(blk, "interest_rate", None)
            rate = float(rate) if isinstance(rate, (int, float)) and not isinstance(rate, bool) else _DEBT_DEFAULT_RATES_PCT[kind]
            rows.append({
                "kind": kind, "label": _DEBT_LABELS[kind],
                "outstanding": round(out), "emi": round(_f(getattr(blk, "emi", 0))),
                "rate_pct": rate,
            })
    avalanche = [r["kind"] for r in sorted(rows, key=lambda r: -r["rate_pct"])]
    snowball = [r["kind"] for r in sorted(rows, key=lambda r: r["outstanding"])]
    snow_rows = sorted(rows, key=lambda r: r["outstanding"])
    blizzard = ([snow_rows[0]["kind"]] +
                [r["kind"] for r in sorted(snow_rows[1:], key=lambda r: -r["rate_pct"])]) if snow_rows else []

    return {
        "ratios": {
            "dscr": dscr, "dscr_status": _dscr_status(dscr),
            "dti": dti, "dti_status": _dti_status(dti),
            "dni": dni, "dni_status": _dni_status(dni),
            "total_debt_outstanding": round(total_debt),
            "annual_income": round(_f(scal.get("debt_annual_income"))),
            "annual_emi": round(_f(scal.get("debt_annual_emi"))),
            "income_available_for_debt_service": round(_f(scal.get("debt_income_for_service"))),
        },
        "loans": rows,
        "avalanche_order": avalanche,
        "snowball_order": snowball,
        "blizzard_order": blizzard,
        "default_strategy": "avalanche",
        "rationale": "Avalanche minimises total interest paid (clear the highest-rate loan first).",
    }


def _apply_excel_to_computed(plan, outputs: dict[str, Any]) -> None:
    """Make the Excel engine the source of truth for the plan's deterministic
    views: the year-by-year cash-flow table, the net-worth series and the
    monthly cash-flow summary all come from the firm's recalculated workbook so
    the main canvas shows exactly what the Computed Excel tab shows.

    Does NOT touch the probabilistic / advisory layers (risk, Monte Carlo,
    scenarios, freedom) — those keep their own pipeline and read these values.
    """
    scal = outputs.get("scalars") or {}
    yoy = (outputs.get("tables") or {}).get("yoy_cashflow") or []

    rows: list[CashFlowRow] = []
    series: list[NetWorthSeriesPoint] = []
    for r in yoy:
        year = int(_f(r.get("year")))
        if year == 0:
            continue
        nw = _f(r.get("net_worth"))
        rows.append(
            CashFlowRow(
                year=year,
                age=int(round(_f(r.get("age")))),
                income=_f(r.get("income_total")),
                expenses=_f(r.get("total_outflow")),     # regular + loan outflow
                taxes=0.0,
                retirement_contributions=0.0,
                other=0.0,
                goal_outflow=abs(_f(r.get("major_withdrawals"))),
                assets=_f(r.get("financial_assets_close")),
                liquid=0.0,
                portfolio=_f(r.get("financial_assets_close")),
                real_estate=_f(r.get("non_financial_close")),
                gold=0.0,
                total_net_worth=nw,
            )
        )
        series.append(NetWorthSeriesPoint(year=year, value=nw))

    if rows:
        plan.computed.cash_flow_table = rows
        plan.computed.net_worth_series = series
        # Headline = projected net worth AT RETIREMENT — the milestone the plan
        # is built around, well-defined for every client. (The peak can land in
        # year 1 for a plan wrecked by unaffordable near-term goals, which made a
        # misleading "in 1 year" headline.) The net-worth chart still shows the
        # full trajectory including any post-retirement drawdown / shortfall.
        retire_age = _f((outputs.get("scalars") or {}).get("retire_age"))
        retire_row = None
        if retire_age:
            retire_row = next((r for r in rows if r.age >= retire_age), None)
        target = retire_row or max(rows, key=lambda r: r.total_net_worth)
        plan.computed.headline_amount_at_horizon = target.total_net_worth
        plan.computed.horizon_years = max(1, target.year - rows[0].year)

    # Build the Excel-authoritative CFP snapshot the canvas tabs AND the agent's
    # cfp_plan tool read. Structure matches what the frontend (GoalsView /
    # InsuranceView / TaxView / DebtPaydownView / cash-flow cards) expects; every
    # number is straight from the recalculated firm workbook so the tabs and the
    # Computed-Excel tab agree. Only the genuinely-heuristic detail that the firm
    # sheet doesn't model (the retirement 3-case stretch search) is preserved by
    # merging rather than replacing the whole cfp dict.
    cfp = dict(plan.computed.cfp or {})
    cfp["source"] = "excel_engine"

    goal_blocks = _excel_goal_blocks(outputs, plan)
    if goal_blocks:
        cfp["goal_blocks"] = goal_blocks
    insurance = _excel_insurance(scal)
    if insurance:
        cfp["insurance"] = insurance
    retirement = _excel_retirement(scal)
    if retirement:
        # Keep any Python-built retirement detail (the 3-case glide the firm
        # sheet doesn't expose) but override its headline corpus / SIP numbers
        # with the workbook's authoritative values.
        cfp["retirement"] = {**(cfp.get("retirement") or {}), **retirement}
    tax_regime = _excel_tax_regime(scal)
    if tax_regime:
        cfp["tax_regime"] = tax_regime
    debt = _excel_debt(scal, plan)
    if debt:
        cfp["debt"] = debt

    # Headline summary — all from Excel scalars so the cfp_plan tool and the
    # summary card report exactly the workbook's numbers.
    headline = {
        "current_age": _f(scal.get("current_age")),
        "retirement_age": _f(scal.get("retire_age")),
        "years_to_retire": _f(scal.get("years_to_retire")),
        "retirement_corpus_required": _f(scal.get("retirement_corpus_required")),
        "retirement_gross_sip_monthly": _f(scal.get("retirement_gross_monthly_sip")),
        "retirement_ongoing_sip_monthly": _f(scal.get("retirement_ongoing_monthly_sip")),
        "additional_insurance_cover_required": _f(scal.get("life_cover_additional")),
        "net_worth": _f(scal.get("net_worth")),
        "total_assets": _f(scal.get("total_assets")),
        "total_loans": _f(scal.get("total_loans")),
        "recommended_tax_regime": (cfp.get("tax_regime") or {}).get("recommended_regime"),
        "annual_tax_savings_with_recommended": (cfp.get("tax_regime") or {}).get("annual_savings_with_recommended"),
        "dscr": (cfp.get("debt") or {}).get("ratios", {}).get("dscr"),
        "dti": (cfp.get("debt") or {}).get("ratios", {}).get("dti"),
        "dni": (cfp.get("debt") or {}).get("ratios", {}).get("dni"),
    }
    cfp["summary"] = {**(cfp.get("summary") or {}), **headline}

    # Monthly cash-flow summary card reads computed.cfp.summary — feed it the
    # firm workbook's year-0 monthly figures so it tallies with the Excel.
    if yoy:
        y0 = next((r for r in yoy if int(_f(r.get("year"))) >= 1), yoy[0])
        summary = {
            "monthly_income": round(_f(y0.get("income_total")) / 12, 2),
            "monthly_expenses": round(_f(y0.get("expenses")) / 12, 2),
            "monthly_emi": round(_f(y0.get("loan_repayment")) / 12, 2),
            "monthly_existing_sip": _f(scal.get("monthly_investments_ongoing")),
        }
        cfp["summary"] = {**(cfp.get("summary") or {}), **summary}
        # Feed the canvas's "Excel" year-by-year table directly from the firm
        # workbook so it shows the same numbers as the Computed Excel tab
        # (field names match the frontend's YoyRow shape).
        cfp["yoy_cashflow"] = [
            {
                "year": int(_f(r.get("year"))),
                "age": _f(r.get("age")),
                "income_employment": _f(r.get("income_employment")),
                "income_business": _f(r.get("income_business")),
                "income_rental": _f(r.get("income_rental")),
                "income_other": _f(r.get("income_other")),
                "total_income": _f(r.get("income_total")),
                "expenses": _f(r.get("expenses")),
                "loan_repayment": _f(r.get("loan_repayment")),
                "total_outflow": _f(r.get("total_outflow")),
                "surplus": _f(r.get("surplus")),
                "fa_opening": _f(r.get("fa_opening")),
                "net_annual_cash_savings": _f(r.get("net_annual_cash_savings")),
                "major_withdrawals": _f(r.get("major_withdrawals")),
                "investment_returns": _f(r.get("investment_returns")),
                "lumpsum_deposit_withdrawal": _f(r.get("lumpsum")),
                "financial_assets_closing": _f(r.get("financial_assets_close")),
                "nfa_opening": _f(r.get("nfa_opening")),
                "nfa_appreciation": _f(r.get("nfa_appreciation")),
                "non_financial_assets_closing": _f(r.get("non_financial_close")),
                "net_worth": _f(r.get("net_worth")),
                "net_worth_crore": _f(r.get("net_worth_crore")),
            }
            for r in yoy
            if int(_f(r.get("year"))) > 0
        ]

    plan.computed.cfp = cfp


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

    plan = await get_plan(household_id)

    # Route by format. The firm's native template injects cell-for-cell (exact
    # inputs); any other layout writes the LLM-normalised PlanState into the
    # master. BOTH then get the same dynamic layer (no hardcoded sample values):
    # the firm-template path is passed the plan so it also clears the sample's
    # leaking lumpsums/remarks and allocates the client's real assets to goals.
    # LibreOffice recalc is blocking + CPU/IO heavy → offload to a thread.
    if plan is None:
        populated, outputs = await asyncio.to_thread(compute_from_upload, source)
    elif _is_firm_template(source):
        populated, outputs = await asyncio.to_thread(compute_from_upload, source, plan=plan)
    else:
        populated, outputs = await asyncio.to_thread(compute_from_plan, plan)

    await save_computed_workbook(household_id, populated, outputs)

    # Mirror onto the plan's computed snapshot so the rest of the app sees it.
    if plan is not None:
        plan.computed.excel_outputs = outputs
        _apply_excel_to_computed(plan, outputs)
        await save_plan(plan)

    return outputs


async def recompute_excel(household_id: str) -> Optional[dict[str, Any]]:
    """Recompute the plan through the Excel engine from the CURRENT PlanState.

    Used after an RM edits the plan in chat (add a loan, move a goal, change the
    retirement age, …). Unlike run_excel_plan, this always goes through
    compute_from_plan — the edited plan is the source of truth, the original
    uploaded workbook is stale. Non-fatal: a recalc hiccup leaves the existing
    computed numbers in place rather than failing the chat turn.
    """
    plan = await get_plan(household_id)
    if plan is None:
        return None
    # Nothing to compute from an empty plan (e.g. a household with no income).
    if not (plan.income_details or plan.financial_goals or plan.assumptions.persons):
        return None
    import time as _time
    _t = _time.monotonic()
    try:
        populated, outputs = await asyncio.to_thread(compute_from_plan, plan)
    except Exception:
        _log.error(
            "excel.recompute.failed",
            extra={"household_id": household_id, "category": "excel",
                   "duration_ms": round((_time.monotonic() - _t) * 1000, 1)},
            exc_info=True,
        )
        return None
    _log.info("excel.recompute.done", extra={
        "household_id": household_id, "category": "excel",
        "duration_ms": round((_time.monotonic() - _t) * 1000, 1)})

    await save_computed_workbook(household_id, populated, outputs)
    # Reload in case the plan changed between get_plan and now, then mirror.
    plan = await get_plan(household_id)
    if plan is not None:
        plan.computed.excel_outputs = outputs
        _apply_excel_to_computed(plan, outputs)
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


def _excel_trace(scal: dict[str, Any], cfp: dict) -> list[dict]:
    """A computation trace built from the firm workbook's own values, so the
    cfp_plan tool can still show 'the math' — but every figure is the Excel
    result, not a Python re-derivation. Each step names the firm formula."""
    tr = (cfp.get("tax_regime") or {})
    steps = [
        {"step": "Retirement corpus required",
         "formula": "Retirement Plan!E30 = PV(real return, years in retirement, -annual need) + one-time spends FV",
         "result": _f(scal.get("retirement_corpus_required")), "unit": "INR"},
        {"step": "Retirement SIP needed (gross / ongoing)",
         "formula": "Retirement Plan!E41 (gross) vs E43 (ongoing) → E44 additional",
         "result": _f(scal.get("retirement_gross_monthly_sip")), "unit": "INR/mo"},
        {"step": "Additional life cover required",
         "formula": "Insurance Computation!F38 = required cover − existing − disposable assets",
         "result": _f(scal.get("life_cover_additional")), "unit": "INR"},
        {"step": "Net worth",
         "formula": "11. Inc Exp,Networth,Rec Invest!I53 = total assets − total loans",
         "result": _f(scal.get("net_worth")), "unit": "INR"},
    ]
    if tr:
        steps.append({
            "step": "Income-tax regime choice",
            "formula": "Tax Planning (engine block): old vs new slab tax + 87A + 4% cess → lower wins",
            "result": f"{tr.get('recommended_regime')} (saves ₹{tr.get('annual_savings_with_recommended', 0):,})",
            "unit": "regime"})
    return steps


async def run_cfp(household_id: str) -> dict[str, Any]:
    """Excel-sourced Comprehensive Financial Plan for the agent's `cfp_plan`
    tool. Returns the snapshot assembled purely from the recalculated Excel —
    goal blocks, retirement corpus/SIPs, insurance need, year-by-year cash flow,
    the tax-regime comparison and the debt ratios. NO Python financial math:
    every number is a cell the firm's formulas produced. Shaped like the old
    CFPOutput so the agent renders it unchanged.

    Uses the CACHED Excel snapshot (kept fresh by upload + chat-edit recomputes)
    rather than forcing a recalc — a LibreOffice recalc is a 20-40s CPU-heavy
    subprocess, so firing one on every cfp_plan call would starve the box.
    """
    plan = await get_plan(household_id)
    if plan is None:
        return {"error": "household_not_found"}
    outputs = (plan.computed.excel_outputs
               or await get_or_compute_outputs(household_id)
               or {})
    if not outputs:
        return {
            "error": "no_excel_outputs",
            "message": "No computed workbook yet — upload the CFP input .xlsx "
                       "or add income/goals so the engine can compute.",
        }
    plan = await get_plan(household_id)
    scal = outputs.get("scalars") or {}
    cfp = dict(plan.computed.cfp or {})
    return {
        "source": "excel_engine",
        "summary": cfp.get("summary") or {},
        "goal_blocks": cfp.get("goal_blocks") or [],
        "retirement": cfp.get("retirement") or {},
        "insurance": cfp.get("insurance") or {},
        "tax_regime": cfp.get("tax_regime") or {},
        "debt": cfp.get("debt") or {},
        "yoy_cashflow": cfp.get("yoy_cashflow") or [],
        "scalars": scal,
        "computation_trace": _excel_trace(scal, cfp),
    }
