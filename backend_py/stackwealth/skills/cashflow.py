"""
Cash-flow projection — port of skills/cashflow/index.ts.
Year-by-year + 12-month strip + retirement glide.

Goals deduct from `assets` at their `target_year`. Inflation-adjusted if
`is_target_in_today_money`. Per-goal outflow surfaced on each row so the
canvas / PDF can show *"₹1.20 Cr withdrawn for Elder daughter college in
2040"* instead of the line just dipping silently.
"""
from __future__ import annotations

import calendar
from datetime import datetime
from typing import Any

from ..db import get_plan
from ..types import (
    CashFlowGoalOutflow,
    CashFlowProjection,
    CashFlowRow,
    GlidePoint,
    Goal,
    MonthlyStrip,
    PlanState,
)


# Goal kinds that are one-time future expenses paid from assets.
# "retirement" is excluded — it's a corpus target, not a withdrawal event;
# the retirement-age switch already drives the income/expense glide.
_DRAWDOWN_GOAL_KINDS = {
    "house_purchase",
    "child_education",
    "child_marriage",
    "foreign_travel",
    "other",
}


def _goal_target_in_year(g: Goal, current_year: int, default_inflation: float) -> float:
    """Inflation-adjusted goal amount, scaled from today to the target year.
    Returns 0 if the goal has no target_amount."""
    if not g.target_amount or g.target_amount <= 0:
        return 0.0
    if not g.is_target_in_today_money:
        return float(g.target_amount)
    target_year = g.target_year or (current_year + (g.horizon_years or 0))
    years_until = max(0, target_year - current_year)
    inflation = g.inflation_assumed if g.inflation_assumed is not None else default_inflation
    return float(g.target_amount) * ((1 + inflation) ** years_until)


async def project(args: dict[str, Any]) -> dict | CashFlowProjection:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    return compute_cashflow(plan, args.get("horizon_years") or 45)


def compute_cashflow(plan: PlanState, horizon: int) -> CashFlowProjection:
    fsi = plan.freedom_score_inputs
    start_year = datetime.now().year
    start_age = fsi.age or 30
    monthly_income = fsi.monthly_income or 0
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0
    equity_pct = (fsi.equity_allocation_percent or 50) / 100
    expected_return = equity_pct * 0.10 + (1 - equity_pct) * 0.07
    inflation = plan.assumptions.inflation
    taxes = (
        plan.assumptions.taxes.federal
        + plan.assumptions.taxes.state
        + plan.assumptions.taxes.capital_gains
    )
    retirement_age = plan.personal_details.retirement_age_target or 60
    assets = (fsi.portfolio_current_value or 0) + (fsi.liquid_assets_current_value or 0)
    rows: list[CashFlowRow] = []

    # Pre-bucket goals by their target_year so each iteration is O(goals/year),
    # not O(goals × years). Skip goals whose kind doesn't drive a drawdown
    # (e.g. "retirement" — that's a corpus target, not a withdrawal event)
    # and goals with no target_year + no horizon_years (can't place on timeline).
    goals_by_year: dict[int, list[Goal]] = {}
    for g in plan.financial_goals:
        if g.kind not in _DRAWDOWN_GOAL_KINDS:
            continue
        target_year = g.target_year or (start_year + (g.horizon_years or 0))
        # Goals already in the past or this year still need to be deducted
        # this year — don't skip them. Goals beyond the horizon are dropped.
        if target_year > start_year + horizon - 1:
            continue
        goals_by_year.setdefault(max(target_year, start_year), []).append(g)

    for i in range(horizon):
        year = start_year + i
        age = start_age + i
        earning = age < retirement_age
        annual_income = monthly_income * 12 * ((1 + inflation * 0.5) ** i) if earning else 0
        annual_expenses = monthly_expenses * 12 * ((1 + inflation) ** i)
        annual_emi = monthly_emi * 12 if earning else 0
        annual_tax = annual_income * (taxes * 0.4)  # simplified effective tax
        retirement_contrib = max(0.0, annual_income * 0.20) if earning else 0
        net = annual_income - annual_expenses - annual_emi - annual_tax
        assets = assets * (1 + expected_return) + max(net, 0)

        # Goal drawdowns happen AFTER the year's growth + savings — same as
        # paying a large expense in December. Inflation-adjust each goal
        # forward from today to its target year.
        breakdown: list[CashFlowGoalOutflow] = []
        goal_outflow_total = 0.0
        for g in goals_by_year.get(year, []):
            amt = _goal_target_in_year(g, start_year, inflation)
            if amt <= 0:
                continue
            breakdown.append(
                CashFlowGoalOutflow(goal_id=g.id, goal_name=g.goal_name, amount=round(amt))
            )
            goal_outflow_total += amt
        # Clamp at zero — a real household can't go below liquid==0 here.
        # The shortfall is implicit when the projection flattens at 0; the
        # canvas can call it out separately if needed.
        assets = max(0.0, assets - goal_outflow_total)

        rows.append(
            CashFlowRow(
                year=year,
                age=age,
                assets=round(assets),
                income=round(annual_income),
                expenses=round(annual_expenses),
                taxes=round(annual_tax),
                retirement_contributions=round(retirement_contrib),
                other=0,
                total_net_worth=round(assets),
                goal_outflow=round(goal_outflow_total),
                goal_outflow_breakdown=breakdown,
            )
        )

    monthly_strip_next_12mo = [
        MonthlyStrip(
            month=calendar.month_abbr[m + 1],
            inflow=monthly_income,
            outflow=monthly_expenses + monthly_emi,
        )
        for m in range(12)
    ]
    retirement_glide = [GlidePoint(year=r.year, balance=r.total_net_worth) for r in rows]
    return CashFlowProjection(
        rows=rows,
        monthly_strip_next_12mo=monthly_strip_next_12mo,
        retirement_glide=retirement_glide,
    )
