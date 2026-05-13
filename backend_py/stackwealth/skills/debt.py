"""
Debt-paydown projection — per-loan amortization schedules + an aggregate
year-by-year EMI / interest / principal breakdown across every loan in
`loans_liabilities`. Lets the canvas show "when does each loan end" and
"how much interest am I paying over the term" — gaps the existing
cashflow projection doesn't surface.

Math:
- Standard EMI amortization. Given outstanding `P`, annual interest `r`,
  monthly EMI `E`, we walk year by year — splitting each year's 12 EMIs
  into interest + principal at compound monthly rate `r/12`.
- When `interest_rate` is missing from the LoanBlock we fall back to a
  type-based default (home 8.5%, car 9.5%, personal 12%, credit card
  24%). A note is surfaced so the user knows the rate was assumed.
- When `tenure_left` is missing we derive it from balance + EMI + rate
  using the standard amortization formula and cap at 30 years.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from ..db import get_plan
from ..types import (
    DebtAmortRow,
    DebtPaydownOutput,
    DebtSchedule,
    LoanBlock,
    PlanState,
)


_DEFAULT_RATES_PCT = {
    "home_loan": 8.5,
    "car_loan": 9.5,
    "personal_loan": 12.0,
    "credit_card_dues": 24.0,
}


async def paydown(args: dict[str, Any]) -> dict | DebtPaydownOutput:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    return compute_debt_paydown(plan)


def compute_debt_paydown(plan: PlanState) -> DebtPaydownOutput:
    start_year = datetime.now().year
    schedules: list[DebtSchedule] = []
    rate_notes: list[str] = []
    loans = plan.loans_liabilities
    for loan_type in ("home_loan", "car_loan", "personal_loan", "credit_card_dues"):
        block: Optional[LoanBlock] = getattr(loans, loan_type, None)
        if block is None:
            continue
        outstanding = block.outstanding_amount or 0
        emi = block.emi or 0
        if outstanding <= 0 or emi <= 0:
            continue

        rate_pct = block.interest_rate
        if rate_pct is None:
            rate_pct = _DEFAULT_RATES_PCT[loan_type]
            rate_notes.append(f"{loan_type}: rate assumed at {rate_pct}%/yr (none on plan)")
        annual_rate = rate_pct / 100.0
        monthly_rate = annual_rate / 12.0

        tenure_years = block.tenure_left
        if tenure_years is None or tenure_years <= 0:
            tenure_years = _solve_tenure_years(outstanding, emi, monthly_rate)
            rate_notes.append(f"{loan_type}: tenure assumed ~{tenure_years:.1f}y (derived)")

        rows = _amortize(outstanding, emi, monthly_rate, tenure_years, start_year)
        total_interest = sum(r.annual_interest for r in rows)
        total_principal = sum(r.annual_principal for r in rows)
        final_year = rows[-1].year if rows else start_year

        schedules.append(
            DebtSchedule(
                loan_type=loan_type,
                outstanding_amount=outstanding,
                emi=emi,
                interest_rate=rate_pct,
                tenure_left_years=tenure_years,
                rows=rows,
                total_interest_paid=round(total_interest),
                total_principal_paid=round(total_principal),
                final_year=final_year,
            )
        )

    aggregate = _aggregate(schedules)
    return DebtPaydownOutput(
        schedules=schedules,
        total_outstanding_today=sum(s.outstanding_amount for s in schedules),
        total_emi_monthly=sum(s.emi for s in schedules),
        total_interest_over_term=round(sum(s.total_interest_paid for s in schedules)),
        aggregate_yearly=aggregate,
        last_emi_year=max((s.final_year for s in schedules), default=start_year),
        note=" · ".join(rate_notes) if rate_notes else None,
    )


def _amortize(
    outstanding: float, emi: float, monthly_rate: float, tenure_years: float, start_year: int
) -> list[DebtAmortRow]:
    """Walk year-by-year, splitting each year's 12 EMIs into interest +
    principal. Stops when balance reaches zero (EMI might over-pay in the
    final year — clip to outstanding) or when we've exceeded the stated
    tenure (clip and surface as a warning candidate)."""
    rows: list[DebtAmortRow] = []
    balance = outstanding
    max_years = int(math.ceil(tenure_years)) + 1  # +1 buffer for floating-point drift
    for i in range(max_years):
        if balance <= 0:
            break
        opening = balance
        annual_interest = 0.0
        annual_principal = 0.0
        annual_emi_paid = 0.0
        for _ in range(12):
            if balance <= 0:
                break
            interest_this_month = balance * monthly_rate
            principal_this_month = emi - interest_this_month
            if principal_this_month <= 0:
                # EMI too small to cover interest — perpetual debt. Cap
                # the row at the interest-only amount so we don't loop.
                annual_interest += interest_this_month
                annual_emi_paid += interest_this_month
                continue
            if principal_this_month > balance:
                # Final payment — only pay what's owed.
                principal_this_month = balance
                this_emi = interest_this_month + principal_this_month
            else:
                this_emi = emi
            balance -= principal_this_month
            annual_interest += interest_this_month
            annual_principal += principal_this_month
            annual_emi_paid += this_emi
        rows.append(
            DebtAmortRow(
                year=start_year + i,
                opening_balance=round(opening),
                annual_emi=round(annual_emi_paid),
                annual_interest=round(annual_interest),
                annual_principal=round(annual_principal),
                closing_balance=round(max(0.0, balance)),
            )
        )
        if balance <= 1:
            break
    return rows


def _solve_tenure_years(outstanding: float, emi: float, monthly_rate: float) -> float:
    """Derive tenure from outstanding/EMI/rate via the standard amortization
    formula: n = -ln(1 - r·P/E) / ln(1+r). Capped at 30y for sanity."""
    if monthly_rate <= 0:
        years = (outstanding / emi) / 12
    else:
        ratio = monthly_rate * outstanding / emi
        if ratio >= 1:
            # EMI can't cover monthly interest — debt grows forever; cap.
            return 30.0
        n_months = -math.log(1 - ratio) / math.log(1 + monthly_rate)
        years = n_months / 12
    return min(30.0, max(0.5, years))


def _aggregate(schedules: list[DebtSchedule]) -> list[DebtAmortRow]:
    """Year-by-year aggregate across all loans. Missing years (after a
    short loan ends but a longer one continues) are zero-padded so the
    canvas chart has a clean continuous timeline."""
    if not schedules:
        return []
    min_year = min(s.rows[0].year for s in schedules if s.rows)
    max_year = max(s.rows[-1].year for s in schedules if s.rows)
    by_year: dict[int, dict[str, float]] = {
        y: {"opening_balance": 0, "annual_emi": 0, "annual_interest": 0,
            "annual_principal": 0, "closing_balance": 0}
        for y in range(min_year, max_year + 1)
    }
    for s in schedules:
        for r in s.rows:
            slot = by_year[r.year]
            slot["opening_balance"] += r.opening_balance
            slot["annual_emi"] += r.annual_emi
            slot["annual_interest"] += r.annual_interest
            slot["annual_principal"] += r.annual_principal
            slot["closing_balance"] += r.closing_balance
    return [
        DebtAmortRow(
            year=y,
            opening_balance=round(v["opening_balance"]),
            annual_emi=round(v["annual_emi"]),
            annual_interest=round(v["annual_interest"]),
            annual_principal=round(v["annual_principal"]),
            closing_balance=round(v["closing_balance"]),
        )
        for y, v in sorted(by_year.items())
    ]
