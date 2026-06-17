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


def compute_debt_ratios(plan: PlanState) -> dict:
    """Excel `Debt Mgt` decision logic — DSCR / DTI / DNI ratios.

    DSCR = (annual_income − annual_living_expenses_excl_emi) / annual_EMI
        threshold <1.25 → "reduce debt" advised.
    DTI  = total_outstanding_debt / annual_income
        threshold >0.50 → "high debt burden".
    DNI  = total_outstanding_debt / total_assets
        threshold >0.30 → "debt-heavy net-worth profile".
    """
    fsi = plan.freedom_score_inputs
    annual_income = (fsi.monthly_income or 0) * 12
    annual_expenses = (fsi.monthly_expenses or 0) * 12
    annual_emi = (fsi.monthly_emi or 0) * 12
    loans = plan.loans_liabilities
    total_debt = sum(
        (getattr(loans, k).outstanding_amount or 0) if getattr(loans, k, None) else 0
        for k in ("home_loan", "car_loan", "personal_loan", "credit_card_dues")
    )
    nw = plan.computed.net_worth
    total_assets = (nw.assets_total or 0)
    income_for_debt = annual_income - annual_expenses
    dscr = (income_for_debt / annual_emi) if annual_emi > 0 else None
    dti = (total_debt / annual_income) if annual_income > 0 else None
    dni = (total_debt / total_assets) if total_assets > 0 else None
    return {
        "dscr": round(dscr, 3) if dscr is not None else None,
        "dscr_status": _ratio_status(dscr, healthy=lambda x: x >= 1.25, watch=lambda x: x >= 1.0),
        "dti": round(dti, 3) if dti is not None else None,
        "dti_status": _ratio_status(dti, healthy=lambda x: x <= 0.35, watch=lambda x: x <= 0.50, invert=True),
        "dni": round(dni, 3) if dni is not None else None,
        "dni_status": _ratio_status(dni, healthy=lambda x: x <= 0.20, watch=lambda x: x <= 0.30, invert=True),
        "total_debt_outstanding": round(total_debt),
        "annual_income": round(annual_income),
        "annual_emi": round(annual_emi),
        "income_available_for_debt_service": round(income_for_debt),
    }


def _ratio_status(value, *, healthy, watch, invert: bool = False) -> str:
    if value is None:
        return "n/a"
    if healthy(value):
        return "healthy"
    if watch(value):
        return "watch"
    return "reduce debt" if not invert else "high"


def compute_repayment_strategies(plan: PlanState) -> dict:
    """Excel `Debt Mgt` repayment ordering — Avalanche / Snowball / Blizzard.

    Avalanche: highest-rate loan first (saves most interest).
    Snowball: smallest-balance first (psychological wins).
    Blizzard: snowball until first cleared, then avalanche the rest.
    """
    loans = plan.loans_liabilities
    rows = []
    for key, label in (
        ("home_loan", "Home loan"),
        ("car_loan", "Car loan"),
        ("personal_loan", "Personal loan"),
        ("credit_card_dues", "Credit card dues"),
    ):
        block = getattr(loans, key, None)
        if not block or not (block.outstanding_amount or 0):
            continue
        rate = block.interest_rate if block.interest_rate is not None else _DEFAULT_RATES_PCT[key]
        rows.append({
            "kind": key,
            "label": label,
            "outstanding": round(block.outstanding_amount or 0),
            "emi": round(block.emi or 0),
            "rate_pct": float(rate),
        })
    avalanche = sorted(rows, key=lambda r: -r["rate_pct"])
    snowball = sorted(rows, key=lambda r: r["outstanding"])
    if snowball:
        blizzard = [snowball[0]] + sorted(snowball[1:], key=lambda r: -r["rate_pct"])
    else:
        blizzard = []
    return {
        "avalanche_order": [r["kind"] for r in avalanche],
        "snowball_order":  [r["kind"] for r in snowball],
        "blizzard_order":  [r["kind"] for r in blizzard],
        "loans": rows,
        "default_strategy": "avalanche",
        "rationale": (
            "Avalanche minimises total interest paid. Snowball is the right "
            "default only when the household needs psychological momentum. "
            "Blizzard combines both — clear the smallest loan first, then attack by rate."
        ),
    }


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
