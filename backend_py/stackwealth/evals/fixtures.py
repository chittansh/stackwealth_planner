"""
Reusable household fixtures for eval cases. Each builder returns a fully
populated `PlanState` ready to save. Keep the values realistic — these
households are used to assert on the math.
"""
from __future__ import annotations

from typing import Callable

from ..types import Goal, PlanState, empty_plan_state


def empty(household_id: str) -> PlanState:
    """A blank plan — used by onboarding-flow cases."""
    return empty_plan_state(household_id)


def bengaluru_single_21yo(household_id: str) -> PlanState:
    """The "Goa house" eval persona — 21yo Bengaluru engineer, single, single
    earner, large surplus, one aggressive house goal. The household that
    surfaced most of the prompt bugs."""
    p = empty_plan_state(household_id)
    p.personal_details.full_name = "Bengaluru Single"
    p.personal_details.city_of_residence = "Bengaluru"
    p.personal_details.city_type = "Metro"
    p.personal_details.marital_status = "single"
    p.personal_details.dependents = 0
    p.personal_details.retirement_age_target = 60
    p.freedom_score_inputs.age = 21
    p.freedom_score_inputs.monthly_income = 150000
    p.freedom_score_inputs.monthly_expenses = 73000
    p.freedom_score_inputs.monthly_emi = 13000
    p.freedom_score_inputs.liquid_assets_current_value = 300000
    p.freedom_score_inputs.equity_allocation_percent = 60
    p.income_details.client_salary_in_hand = 150000
    p.monthly_expenses.rent_or_emi = 40000
    p.monthly_expenses.groceries = 20000
    p.monthly_expenses.other_emis = 13000
    p.financial_goals.append(
        Goal(
            goal_name="Goa house",
            kind="house_purchase",
            target_year=2036,
            target_amount=40000000,
            priority="important",
            horizon_years=11,
            is_target_in_today_money=True,
        )
    )
    return p


def bengaluru_pro_32yo_ready_for_analysis(household_id: str) -> PlanState:
    """A household pre-seeded with enough for `run_full_analysis` to chain
    every stage in one shot. Used by Layer-3 orchestrator cases."""
    p = empty_plan_state(household_id)
    p.personal_details.full_name = "Bengaluru Pro"
    p.personal_details.city_of_residence = "Bengaluru"
    p.personal_details.city_type = "Metro"
    p.personal_details.marital_status = "single"
    p.personal_details.dependents = 0
    p.personal_details.retirement_age_target = 60
    p.freedom_score_inputs.age = 32
    p.freedom_score_inputs.monthly_income = 200000
    p.freedom_score_inputs.monthly_expenses = 80000
    p.freedom_score_inputs.monthly_emi = 0
    p.freedom_score_inputs.liquid_assets_current_value = 1000000
    p.freedom_score_inputs.portfolio_current_value = 1500000
    p.freedom_score_inputs.equity_allocation_percent = 60
    p.income_details.client_salary_in_hand = 200000
    p.financial_goals.append(
        Goal(
            goal_name="Retirement",
            kind="retirement",
            target_year=2054,
            target_amount=50000000,
            priority="essential",
            horizon_years=29,
            is_target_in_today_money=True,
        )
    )
    return p


def mumbai_family_32yo(household_id: str) -> PlanState:
    """Classic Mumbai metro household — dual goals, mid-range income, exists
    primarily to exercise the goal-risk-mismatch reconciliation logic."""
    p = empty_plan_state(household_id)
    p.personal_details.full_name = "Mumbai Family"
    p.personal_details.city_of_residence = "Mumbai"
    p.personal_details.city_type = "Metro"
    p.personal_details.marital_status = "married"
    p.personal_details.dependents = 2
    p.personal_details.retirement_age_target = 60
    p.freedom_score_inputs.age = 32
    p.freedom_score_inputs.monthly_income = 150000
    p.freedom_score_inputs.monthly_expenses = 60000
    p.freedom_score_inputs.monthly_emi = 25000
    p.freedom_score_inputs.liquid_assets_current_value = 300000
    p.freedom_score_inputs.portfolio_current_value = 500000
    p.freedom_score_inputs.equity_allocation_percent = 60
    p.income_details.client_salary_in_hand = 150000
    p.monthly_expenses.rent_or_emi = 25000
    p.monthly_expenses.groceries = 15000
    p.financial_goals.extend(
        [
            Goal(
                goal_name="House",
                kind="house_purchase",
                target_year=2032,
                target_amount=8000000,
                priority="important",
                horizon_years=7,
                is_target_in_today_money=True,
            ),
            Goal(
                goal_name="Retirement",
                kind="retirement",
                target_year=2054,
                target_amount=50000000,
                priority="essential",
                horizon_years=29,
                is_target_in_today_money=True,
            ),
        ]
    )
    return p


def with_risk_set(builder: Callable[[str], PlanState]) -> Callable[[str], PlanState]:
    """Wrap a fixture so the household enters the case with a risk profile
    already computed. Layer-2 cases that need allocation/MC/tax don't waste
    LLM turns running the quiz."""
    from ..skills.allocate import compute_allocation
    from ..skills.risk import compute_risk

    def wrapped(household_id: str) -> PlanState:
        p = builder(household_id)
        p.computed.risk_profile = compute_risk(
            p,
            {
                "volatility_reaction": "hold_steady",
                "risk_return_tradeoff": "C",
                "max_tolerable_loss": "20",
            },
        )
        p.computed.allocation = compute_allocation(p)
        return p

    return wrapped


# ── Async wrappers ─────────────────────────────────────────────────────────


def as_fixture(builder: Callable[[str], PlanState]):
    """`Case.fixture` is async — wrap a sync builder. We keep the builders
    sync because they touch no IO."""

    async def _fx(household_id: str) -> PlanState:
        return builder(household_id)

    return _fx
