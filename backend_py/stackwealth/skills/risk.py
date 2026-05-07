"""
Risk profile — port of skills/risk/index.ts.
3-part Capacity / Need / Willingness, reconciled.
"""
from __future__ import annotations

from typing import Any

from ..db import get_plan
from ..types import Goal, PlanState, RiskOutput

VOL_MAP = {"sell_everything": 10, "sell_some": 30, "hold_steady": 60, "buy_more": 90}
RR_MAP = {"A": 15, "B": 40, "C": 65, "D": 90}
LOSS_MAP = {"0": 10, "10": 30, "20": 55, "30": 75, ">30": 90}
VOL_CAP = {"sell_everything": 30, "sell_some": 50, "hold_steady": 100, "buy_more": 100}


async def assess(args: dict[str, Any]) -> dict | RiskOutput:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    return compute_risk(plan, args.get("willingness") or {})


def _profile_from_score(s: float) -> str:
    if s <= 20:
        return "Conservative"
    if s <= 40:
        return "Moderately Conservative"
    if s <= 60:
        return "Moderate"
    if s <= 75:
        return "Moderately Aggressive"
    return "Aggressive"


def _primary_horizon(goals: list[Goal]) -> int:
    if not goals:
        return 10
    return min((g.horizon_years or 10) for g in goals)


def _bisect_required_return(pv: float, pmt: float, n: int, target: float) -> float:
    if target <= 0 or n <= 0:
        return 0.0
    lo, hi = 0.0, 0.30

    def f(r: float) -> float:
        if r == 0:
            return pv + pmt * n - target
        return pv * ((1 + r) ** n) + pmt * (((1 + r) ** n - 1) / r) - target

    if f(lo) >= 0:
        return lo
    if f(hi) <= 0:
        return hi
    for _ in range(50):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return min(0.25, (lo + hi) / 2)


def _goal_need(g: Goal, inflation: float) -> dict:
    pv = g.current_allocated_amount or 0
    pmt = (g.periodic_contribution or 0) * (12 if g.contribution_frequency == "monthly" else 1)
    n = g.horizon_years or 10
    target = g.target_amount or 0
    if g.is_target_in_today_money and (g.inflation_assumed or inflation):
        target = target * ((1 + (g.inflation_assumed or inflation)) ** n)
    r = g.required_return_override or _bisect_required_return(pv, pmt, n, target)
    if r <= 0.04:
        need = 15
    elif r <= 0.06:
        need = 25
    elif r <= 0.08:
        need = 40
    elif r <= 0.10:
        need = 55
    elif r <= 0.12:
        need = 70
    elif r <= 0.14:
        need = 85
    else:
        need = 95
    if g.priority == "essential":
        priority_w = 1.0
    elif g.priority == "important":
        priority_w = 0.7
    else:
        priority_w = 0.4
    return {
        "goal_name": g.goal_name,
        "need_score": need,
        "required_return": r,
        "priority": priority_w,
    }


def compute_risk(plan: PlanState, w: dict[str, Any]) -> RiskOutput:
    # Willingness
    vol = VOL_MAP.get(w.get("volatility_reaction"), 60)
    rr = RR_MAP.get(w.get("risk_return_tradeoff"), 65)
    loss = LOSS_MAP.get(w.get("max_tolerable_loss"), 55)
    willingness_raw = vol * 0.30 + rr * 0.40 + loss * 0.30
    cap = VOL_CAP.get(w.get("volatility_reaction"), 100)
    willingness_score = min(willingness_raw, cap)

    # Capacity
    fsi = plan.freedom_score_inputs
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0
    liquid = fsi.liquid_assets_current_value or 0
    monthly_income = fsi.monthly_income or 0
    surplus = monthly_income - monthly_expenses - monthly_emi
    surplus_ratio = surplus / monthly_income if monthly_income > 0 else 0
    ef_months = liquid / monthly_expenses if monthly_expenses > 0 else 0
    horizon = _primary_horizon(plan.financial_goals)

    horizon_cap = 30 if horizon <= 2 else 55 if horizon <= 5 else 75 if horizon <= 10 else 100
    stability_cap = 80
    ef_cap = 35 if ef_months < 1 else 55 if ef_months < 3 else 75 if ef_months < 6 else 100
    if surplus_ratio < 0.10:
        surplus_cap = 40
    elif surplus_ratio < 0.20:
        surplus_cap = 55
    elif surplus_ratio < 0.35:
        surplus_cap = 70
    elif surplus_ratio < 0.50:
        surplus_cap = 85
    else:
        surplus_cap = 100
    exp_cap = 75

    caps = {
        "horizon": horizon_cap,
        "stability": stability_cap,
        "ef": ef_cap,
        "surplus": surplus_cap,
        "exp": exp_cap,
    }
    binding_name, capacity_score = min(caps.items(), key=lambda kv: kv[1])
    capacity_profile = _profile_from_score(capacity_score)

    # Need
    investable = [g for g in plan.financial_goals if g.kind != "foreign_travel"]
    goal_needs = [_goal_need(g, plan.assumptions.inflation) for g in investable]
    sorted_needs = sorted(goal_needs, key=lambda x: -(x["need_score"] * x["priority"]))
    driver = sorted_needs[0] if sorted_needs else None
    need_score = driver["need_score"] if driver else 0
    need_profile = _profile_from_score(need_score)

    # Reconciliation
    prudent_ceiling = min(capacity_score, willingness_score)
    if need_score <= prudent_ceiling - 15:
        recommended = max(need_score + 5, 20)
    else:
        recommended = min(need_score, prudent_ceiling)
    recommended_profile = _profile_from_score(recommended)

    if need_score <= prudent_ceiling and abs(need_score - prudent_ceiling) <= 15:
        alignment = "aligned"
    elif need_score < prudent_ceiling - 15:
        alignment = "need_below_ceiling"
    elif need_score > prudent_ceiling:
        alignment = "goal_risk_mismatch"
    elif not investable:
        alignment = "need_unavailable"
    else:
        alignment = "incomplete"

    warnings: list[str] = []
    if alignment == "goal_risk_mismatch":
        warnings.append("Goals require more risk than is prudent. Consider planning changes.")
    if ef_months < 3:
        warnings.append("Emergency fund covers less than 3 months. Build reserves before adding risk.")

    goal_actions: list[str] = []
    if alignment == "goal_risk_mismatch":
        goal_actions.extend(
            [
                "Increase periodic contribution",
                "Extend horizon",
                "Reduce target amount",
                "Split goal into essential and aspirational",
            ]
        )

    return RiskOutput(
        capacity_score=round(capacity_score),
        capacity_profile=capacity_profile,
        capacity_binding_cap=binding_name,
        need_score=round(need_score),
        need_profile=need_profile,
        need_primary_goal=(driver or {}).get("goal_name"),
        need_driver_goals=[g["goal_name"] for g in goal_needs[:3]],
        willingness_score=round(willingness_score),
        willingness_raw_score=round(willingness_raw, 2),
        willingness_profile=_profile_from_score(willingness_score),
        prudent_ceiling=round(prudent_ceiling),
        recommended_score=round(recommended),
        recommended_profile=recommended_profile,
        alignment_status=alignment,  # type: ignore[arg-type]
        key_warnings=warnings,
        goal_actions=goal_actions,
    )
