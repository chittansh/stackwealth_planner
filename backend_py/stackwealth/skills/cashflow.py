"""
Cash-flow projection — port of skills/cashflow/index.ts.
Year-by-year + 12-month strip + retirement glide.
"""
from __future__ import annotations

import calendar
from datetime import datetime
from typing import Any

from ..db import get_plan
from ..types import CashFlowProjection, CashFlowRow, GlidePoint, MonthlyStrip, PlanState


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
