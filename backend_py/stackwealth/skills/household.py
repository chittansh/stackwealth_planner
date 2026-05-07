"""
Household merge — port of skills/household/merge.ts.
Combines N households into one. Sums monetary fields, unions repeatable
lists, max-takes insurance covers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..db import get_plan, save_plan
from ..types import (
    InsuranceBlock,
    LoanBlock,
    PlanState,
    empty_plan_state,
)


async def preview(args: dict[str, Any]) -> dict[str, Any]:
    plans = await _load_all(args["household_ids"])
    return _summary(plans)


async def merge(args: dict[str, Any]) -> dict[str, str]:
    plans = await _load_all(args["household_ids"])
    parent = _merge_many(plans)
    await save_plan(parent)
    return {"parent_household_id": parent.household_id}


async def _load_all(ids: list[str]) -> list[PlanState]:
    out = []
    for hid in ids:
        p = await get_plan(hid)
        if p:
            out.append(p)
    return out


def _sum_optionals(o: Any) -> float:
    if hasattr(o, "model_dump"):
        o = o.model_dump()
    if not isinstance(o, dict):
        return 0.0
    return sum(v for v in o.values() if isinstance(v, (int, float)))


def _summary(plans: list[PlanState]) -> dict[str, Any]:
    combined_assets = 0.0
    combined_income_monthly = 0.0
    combined_expenses_monthly = 0.0
    combined_goals_count = 0
    for p in plans:
        combined_assets += p.computed.net_worth.assets_total or 0
        combined_income_monthly += (
            (p.income_details.client_salary_in_hand or 0)
            + (p.income_details.spouse_salary_in_hand or 0)
            + (p.income_details.client_business_income or 0)
            + (p.income_details.client_rental_income or 0)
        )
        combined_expenses_monthly += _sum_optionals(p.monthly_expenses)
        combined_goals_count += len(p.financial_goals)
    return {
        "parent_household_id": "preview",
        "combined_assets": combined_assets,
        "combined_income_monthly": combined_income_monthly,
        "combined_expenses_monthly": combined_expenses_monthly,
        "combined_goals_count": combined_goals_count,
    }


def _merge_many(plans: list[PlanState]) -> PlanState:
    parent = empty_plan_state(f"hh-{uuid4().hex[:8]}")
    parent.personal_details.full_name = " + ".join(
        (p.personal_details.full_name or "Member") for p in plans
    )
    if plans:
        parent.personal_details.city_of_residence = plans[0].personal_details.city_of_residence
        parent.personal_details.city_type = plans[0].personal_details.city_type or "Non-metro"

    income_keys = (
        "client_salary_in_hand",
        "spouse_salary_in_hand",
        "client_business_income",
        "client_rental_income",
        "client_other_income",
    )
    for k in income_keys:
        total = sum((getattr(p.income_details, k) or 0) for p in plans)
        if total:
            setattr(parent.income_details, k, total)

    expense_keys = parent.monthly_expenses.model_fields.keys() if plans else []
    for k in expense_keys:
        total = sum((getattr(p.monthly_expenses, k) or 0) for p in plans)
        if total:
            setattr(parent.monthly_expenses, k, total)

    for p in plans:
        parent.mutual_funds.extend(p.mutual_funds)
        parent.equity_stocks.extend(p.equity_stocks)
        parent.fixed_income.extend(p.fixed_income)
        parent.financial_goals.extend(p.financial_goals)
        parent.evidence.extend(p.evidence)
        parent.assumptions.persons.extend(p.assumptions.persons)

    parent.liquid_capital.savings_account_balance = sum(
        (p.liquid_capital.savings_account_balance or 0) for p in plans
    )
    parent.emergency_fund.total_emergency_corpus = sum(
        (p.emergency_fund.total_emergency_corpus or 0) for p in plans
    )

    for k in ("home_loan", "car_loan", "personal_loan", "credit_card_dues"):
        outstanding = 0.0
        emi = 0.0
        rate = 0.0
        tenure = 0.0
        n = 0
        for p in plans:
            b = getattr(p.loans_liabilities, k)
            if not b:
                continue
            outstanding += b.outstanding_amount or 0
            emi += b.emi or 0
            if isinstance(b.interest_rate, (int, float)):
                rate += b.interest_rate
                n += 1
            if isinstance(b.tenure_left, (int, float)) and b.tenure_left > tenure:
                tenure = b.tenure_left
        if outstanding > 0 or emi > 0:
            setattr(
                parent.loans_liabilities,
                k,
                LoanBlock(
                    outstanding_amount=outstanding,
                    emi=emi,
                    interest_rate=(rate / n) if n else None,
                    tenure_left=tenure or None,
                ),
            )

    for k in ("term_plan", "health_insurance", "family_floater", "ulip_or_endowment"):
        cover = 0.0
        premium = 0.0
        company = None
        for p in plans:
            b = getattr(p.insurance_details, k)
            if not b:
                continue
            cover = max(cover, b.cover_amount or 0)
            premium += b.annual_premium or 0
            company = company or b.company
        if cover > 0 or premium > 0:
            setattr(
                parent.insurance_details,
                k,
                InsuranceBlock(
                    company=company,
                    cover_amount=cover or None,
                    annual_premium=premium or None,
                ),
            )

    parent.freedom_score_inputs.monthly_income = sum(
        (p.freedom_score_inputs.monthly_income or 0) for p in plans
    )
    parent.freedom_score_inputs.monthly_expenses = sum(
        (p.freedom_score_inputs.monthly_expenses or 0) for p in plans
    )
    parent.freedom_score_inputs.portfolio_current_value = sum(
        (p.freedom_score_inputs.portfolio_current_value or 0) for p in plans
    )
    parent.freedom_score_inputs.liquid_assets_current_value = sum(
        (p.freedom_score_inputs.liquid_assets_current_value or 0) for p in plans
    )
    parent.freedom_score_inputs.age = max(
        (p.freedom_score_inputs.age or 0) for p in plans
    ) if plans else None
    if plans:
        parent.freedom_score_inputs.equity_allocation_percent = sum(
            (p.freedom_score_inputs.equity_allocation_percent or 0) for p in plans
        ) / max(1, len(plans))

    parent.last_updated_at = datetime.now(timezone.utc).isoformat()
    return parent
