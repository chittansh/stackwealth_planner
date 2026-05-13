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
    # Equity-return assumption comes from `assumptions.growth.investment` so
    # the scenarios card's "equity drawdown shock" slider (which mutates that
    # field) actually moves the projection. Default 0.10 matches the prior
    # hardcoded value, so households that haven't touched assumptions stay on
    # the same curve.
    equity_growth = plan.assumptions.growth.investment if plan.assumptions.growth.investment > 0 else 0.10
    debt_return = 0.07
    expected_return = equity_pct * equity_growth + (1 - equity_pct) * debt_return
    # Cash earns ~4% (assumptions.growth.cash); used for the un-invested cash
    # bucket when an explicit SIP is set.
    cash_return = plan.assumptions.growth.cash if plan.assumptions.growth.cash > 0 else 0.04
    inflation = plan.assumptions.inflation
    taxes = (
        plan.assumptions.taxes.federal
        + plan.assumptions.taxes.state
        + plan.assumptions.taxes.capital_gains
    )
    retirement_age = plan.personal_details.retirement_age_target or 60

    # Two-pool model so scenario sliders that change SIP move the projection:
    #   portfolio — grows at expected_return (equity-blended)
    #   liquid    — grows at cash_return (cash/FD rate)
    # If the user has set explicit `monthly_investments.mutual_fund_sip` (and
    # related SIPs), the cashflow treats that as the amount invested per year;
    # the remaining surplus accumulates in the liquid pool. If the user has
    # NOT specified any SIP, we fall back to the historical "all surplus
    # invested" model so existing households don't see regressions.
    portfolio = fsi.portfolio_current_value or 0
    liquid = fsi.liquid_assets_current_value or 0
    mi = plan.monthly_investments
    monthly_sip_total = 0.0
    for attr in ("mutual_fund_sip", "nps", "ppf", "rd", "direct_equity"):
        v = getattr(mi, attr, None) if mi else None
        if isinstance(v, (int, float)) and v > 0:
            monthly_sip_total += v
    sip_explicit = monthly_sip_total > 0
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
        # Income grows at FULL inflation (real income stays flat). The
        # previous half-inflation rule forced real income to halve over a
        # 30-year career, pushing surplus negative purely from model bias
        # even for healthy savers. Households that explicitly expect real
        # career growth should add it via `assumptions.real_income_growth`
        # later.
        annual_income = monthly_income * 12 * ((1 + inflation) ** i) if earning else 0
        annual_expenses = monthly_expenses * 12 * ((1 + inflation) ** i)
        annual_emi = monthly_emi * 12 if earning else 0
        annual_tax = annual_income * (taxes * 0.4)  # simplified effective tax
        retirement_contrib = max(0.0, annual_income * 0.20) if earning else 0
        surplus = annual_income - annual_expenses - annual_emi - annual_tax

        # Allocate surplus between portfolio (investments) and liquid (cash).
        if sip_explicit and earning:
            # SIP scales at inflation + an optional step-up rate. Step-up
            # captures the "I'll bump my SIP by 10%/yr as my income grows"
            # commitment that goes beyond inflation-matching. Defaults to 0
            # so an unspecified household keeps the inflation-only path.
            step_up = plan.assumptions.sip_annual_step_up_pct or 0.0
            annual_sip = monthly_sip_total * 12 * ((1 + inflation + step_up) ** i)
            invested_this_year = max(0.0, min(annual_sip, surplus))
            cash_added_this_year = max(0.0, surplus - invested_this_year)
        else:
            # Legacy "all surplus invested" path — no regression for
            # households that haven't told us a specific SIP.
            invested_this_year = max(0.0, surplus)
            cash_added_this_year = 0.0

        portfolio = portfolio * (1 + expected_return) + invested_this_year
        liquid = liquid * (1 + cash_return) + cash_added_this_year

        # Goal drawdowns: tap liquid first (rational household behavior — use
        # cash before redeeming investments), then portfolio for any shortfall.
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
        remaining = goal_outflow_total
        from_liquid = min(liquid, remaining)
        liquid -= from_liquid
        remaining -= from_liquid
        from_portfolio = min(portfolio, remaining)
        portfolio -= from_portfolio

        assets = portfolio + liquid

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
