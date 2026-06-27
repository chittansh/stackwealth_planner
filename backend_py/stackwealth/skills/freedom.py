"""
Freedom Score — port of skills/freedom/index.ts.

5 pillars (weights 15/20/35/15/15), all clamped 0..100. City multiplier
1.25 metro / 1.00 non-metro.
"""
from __future__ import annotations

import math
from typing import Any

from ..db import get_plan
from ..tracing import traced_calc
from ..types import FreedomOutput, FreedomPillars, PlanState

WEIGHTS = {
    "liquidity": 0.15,
    "debt": 0.20,
    "investment": 0.35,
    "discipline": 0.15,
    "risk": 0.15,
}


async def score(args: dict[str, Any]) -> dict | FreedomOutput:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    return compute_freedom(plan)


def _clamp(n: float, lo: float, hi: float) -> float:
    if not isinstance(n, (int, float)) or n != n:  # NaN check
        return lo
    return max(lo, min(hi, n))


def _sum_optionals(o: Any) -> float:
    if hasattr(o, "model_dump"):
        o = o.model_dump()
    if not isinstance(o, dict):
        return 0.0
    return sum(v for v in o.values() if isinstance(v, (int, float)))


def _sum_debts(plan: PlanState) -> float:
    total = 0.0
    for k in ("home_loan", "car_loan", "personal_loan", "credit_card_dues"):
        b = getattr(plan.loans_liabilities, k, None)
        if b and b.outstanding_amount:
            total += b.outstanding_amount
    return total


def _dependents_to_count(d: Any) -> int:
    """`personal_details.dependents` is loosely typed (int or freeform str).
    Best-effort: if int → use as-is; if str → count distinct name/phrase
    tokens (commas / 'and' / '+' separators) as a proxy for dependent count.
    Empty/None → 0."""
    if d is None:
        return 0
    if isinstance(d, (int, float)):
        return max(0, int(d))
    s = str(d).strip()
    if not s:
        return 0
    # Replace common separators with commas so a single split works.
    import re as _re
    pieces = [p for p in _re.split(r"\s*(?:,| and | & |\+)\s*", s, flags=_re.I) if p.strip()]
    return max(1, len(pieces))


def _dependent_life_mult(d: int) -> float:
    if d <= 0:
        return 0.5
    if d == 1:
        return 1.0
    if d == 2:
        return 1.2
    return 1.5


def _dependent_med_mult(d: int) -> float:
    return min(4.0, max(1.0, d + 1.0))


def _estimate_freedom_age(plan: PlanState) -> float:
    fsi = plan.freedom_score_inputs
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_income = fsi.monthly_income or 0
    portfolio = fsi.portfolio_current_value or 0
    age = fsi.age or 30
    expected_return = (fsi.equity_allocation_percent or 50) / 100 * 0.10 + 0.07
    annual_need = monthly_expenses * 12
    if annual_need == 0:
        return float(age)
    target = annual_need * 25
    annual_savings = (monthly_income - monthly_expenses) * 12
    if annual_savings <= 0:
        return age + 60
    # FV = PV(1+r)^n + PMT * (((1+r)^n - 1) / r) → bisect for n
    lo, hi = 0.0, 80.0
    for _ in range(50):
        mid = (lo + hi) / 2
        fv = portfolio * ((1 + expected_return) ** mid) + annual_savings * (
            ((1 + expected_return) ** mid - 1) / expected_return
        )
        if fv < target:
            lo = mid
        else:
            hi = mid
    return age + lo


@traced_calc("calc.freedom")
def compute_freedom(plan: PlanState) -> FreedomOutput:
    fsi = plan.freedom_score_inputs
    monthly_income = fsi.monthly_income or 0
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0
    liquid = fsi.liquid_assets_current_value
    if liquid is None:
        liquid = _sum_optionals(plan.liquid_capital)
    portfolio = fsi.portfolio_current_value or 0
    equity_pct = fsi.equity_allocation_percent or 0
    dependents_raw = plan.personal_details.dependents
    dependents = _dependents_to_count(dependents_raw)
    annual_income = monthly_income * 12
    city_mult = 1.25 if (plan.personal_details.city_type or "Non-metro") == "Metro" else 1.0

    # Liquidity pillar
    months_cover = liquid / monthly_expenses if monthly_expenses > 0 else 0
    liquidity = _clamp((months_cover / 6) * 100, 0, 100)

    # Debt pillar
    emi_to_income = monthly_emi / monthly_income if monthly_income > 0 else 0
    emi_score = max(0, (1 - emi_to_income / 0.5) * 100)
    total_assets = (fsi.liquid_assets_current_value or 0) + portfolio
    debts = _sum_debts(plan)
    if total_assets > 0:
        dta_score = max(0, (1 - debts / total_assets / 0.6) * 100)
    else:
        dta_score = 50
    debt = _clamp(emi_score * 0.6 + dta_score * 0.4, 0, 100)

    # Investment pillar
    portfolio_vs_income = min(portfolio / (annual_income * 5), 1) if annual_income > 0 else 0
    equity_fit = _clamp(equity_pct / 100 * 100, 0, 100)
    investment = _clamp(portfolio_vs_income * 60 + equity_fit * 0.4, 0, 100)

    # Discipline pillar
    savings = monthly_income - monthly_expenses - monthly_emi
    savings_rate = savings / monthly_income if monthly_income > 0 else 0
    savings_score = _clamp((savings_rate / 0.30) * 100, 0, 100)
    sip_score = 70  # proxy until SIP consistency wired
    target_age = plan.personal_details.retirement_age_target or 60
    estimated_age = _estimate_freedom_age(plan)
    timeline_score = 100 if estimated_age <= target_age else max(0, 100 - (estimated_age - target_age) * 10)
    discipline = _clamp(savings_score * 0.45 + sip_score * 0.25 + timeline_score * 0.30, 0, 100)

    # Risk pillar
    required_life_cover = annual_income * 10 * _dependent_life_mult(dependents) * city_mult
    required_medical_cover = 500_000 * _dependent_med_mult(dependents) * city_mult
    life_cover = (plan.insurance_details.term_plan and plan.insurance_details.term_plan.cover_amount) or 0
    med_cover = (
        plan.insurance_details.health_insurance and plan.insurance_details.health_insurance.cover_amount
    ) or 0
    life_score = min((life_cover / required_life_cover) * 100, 100) if required_life_cover > 0 else 0
    med_score = min((med_cover / required_medical_cover) * 100, 100) if required_medical_cover > 0 else 0
    risk = _clamp(life_score * 0.6 + med_score * 0.4, 0, 100)

    raw = (
        liquidity * WEIGHTS["liquidity"]
        + debt * WEIGHTS["debt"]
        + investment * WEIGHTS["investment"]
        + discipline * WEIGHTS["discipline"]
        + risk * WEIGHTS["risk"]
    )
    profile_mult = 1.0
    final = _clamp(raw * profile_mult, 0, 100)

    return FreedomOutput(
        raw_weighted_score=round(raw, 2),
        profile_strength_multiplier=profile_mult,
        final_score=round(final, 2),
        pillars=FreedomPillars(
            liquidity=round(liquidity, 2),
            debt=round(debt, 2),
            investment=round(investment, 2),
            discipline=round(discipline, 2),
            risk=round(risk, 2),
        ),
        estimated_freedom_age=round(estimated_age, 1),
        freedom_age_gap=max(0, round(estimated_age - target_age, 1)),
        city_cover_multiplier=city_mult,
        required_life_cover=round(required_life_cover),
        required_medical_cover=round(required_medical_cover),
    )
