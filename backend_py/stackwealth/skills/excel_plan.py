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
from ..types import CashFlowRow, NetWorthSeriesPoint


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
        cfp = dict(plan.computed.cfp or {})
        cfp["summary"] = {**(cfp.get("summary") or {}), **summary}
        cfp["source"] = "excel_engine"
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

    # Route by format. The firm's native template injects cell-for-cell (exact).
    # Any other layout goes through the LLM-normalised PlanState → master writer,
    # which makes the engine format-agnostic. Fall back to direct injection only
    # if we somehow have no plan to write from.
    # LibreOffice recalc is blocking + CPU/IO heavy → offload to a thread.
    if _is_firm_template(source) or plan is None:
        populated, outputs = await asyncio.to_thread(compute_from_upload, source)
    else:
        populated, outputs = await asyncio.to_thread(compute_from_plan, plan)

    await save_computed_workbook(household_id, populated, outputs)

    # Mirror onto the plan's computed snapshot so the rest of the app sees it.
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
