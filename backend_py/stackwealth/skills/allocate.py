"""
India tactical allocator — port of skills/allocate/index.ts.
Strategic anchor by risk band → bounded tactical overlay using signals.
"""
from __future__ import annotations

from typing import Any

from ..db import get_plan
from ..types import (
    AllocationBuckets,
    AllocationOutput,
    EquitySplit,
    PlanState,
    SectorThemeViews,
    SignalEntry,
)
from .signals import get_signals, regime_from_blocks

STRATEGIC = {
    "Conservative": {"equity": 20, "debt": 60, "gold": 15, "cash": 5},
    "Moderately Conservative": {"equity": 35, "debt": 45, "gold": 15, "cash": 5},
    "Moderate": {"equity": 50, "debt": 35, "gold": 10, "cash": 5},
    "Moderately Aggressive": {"equity": 65, "debt": 25, "gold": 7, "cash": 3},
    "Aggressive": {"equity": 80, "debt": 12, "gold": 5, "cash": 3},
}

EQUITY_SPLIT = {
    "Conservative": {"large": 85, "mid": 10, "small": 5},
    "Moderately Conservative": {"large": 75, "mid": 15, "small": 10},
    "Moderate": {"large": 65, "mid": 20, "small": 15},
    "Moderately Aggressive": {"large": 55, "mid": 25, "small": 20},
    "Aggressive": {"large": 45, "mid": 30, "small": 25},
}

TACTICAL_BAND = {
    "Conservative": {"equity": 4, "gold": 3, "cash": 3},
    "Moderately Conservative": {"equity": 6, "gold": 4, "cash": 3},
    "Moderate": {"equity": 8, "gold": 5, "cash": 4},
    "Moderately Aggressive": {"equity": 10, "gold": 5, "cash": 5},
    "Aggressive": {"equity": 12, "gold": 5, "cash": 5},
}


async def recommend(args: dict[str, Any]) -> dict | AllocationOutput:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    if not plan.computed.risk_profile or not plan.computed.risk_profile.recommended_score:
        return {"error": "risk_gate_required"}
    return compute_allocation(plan)


def compute_allocation(plan: PlanState) -> AllocationOutput:
    band = plan.computed.risk_profile.recommended_profile  # type: ignore[union-attr]
    strategic = STRATEGIC.get(band) or STRATEGIC["Moderate"]
    equity_split = EQUITY_SPLIT.get(band) or EQUITY_SPLIT["Moderate"]

    snap = get_signals()
    regime = regime_from_blocks(snap["blocks"])
    composite = regime["score"]
    regime_label = regime["label"]

    cap = (TACTICAL_BAND.get(band) or TACTICAL_BAND["Moderate"])["equity"]
    if composite >= 4:
        desired = cap
    elif composite >= 1:
        desired = cap * 0.5
    elif composite >= -1:
        desired = 0
    elif composite >= -4:
        desired = -cap * 0.5
    else:
        desired = -cap

    if snap["blocks"]["valuation"]["score"] <= -2 and desired > 0:
        desired = 0

    equity_shift = round(max(-cap, min(cap, desired)))
    recommended_allocation = AllocationBuckets(
        equity=max(0, min(100, strategic["equity"] + equity_shift)),
        debt=max(0, min(100, strategic["debt"] - equity_shift)),
        gold=strategic["gold"],
        cash=strategic["cash"],
    )

    internal_shift = 5 if composite > 0 else (-5 if composite < 0 else 0)
    recommended_equity_split = EquitySplit(
        large=max(0, min(100, equity_split["large"] + (-internal_shift if internal_shift < 0 else 0))),
        mid=max(0, min(100, equity_split["mid"] + (round(internal_shift / 2) if internal_shift > 0 else 0))),
        small=max(
            0,
            min(
                100,
                equity_split["small"]
                + (round(internal_shift / 2) if internal_shift > 0 else round(internal_shift / 2)),
            ),
        ),
    )

    macro = snap["blocks"]["macro"]["score"]
    debt_duration_stance = "extend" if macro > 0 else ("shorten" if macro < 0 else "neutral")

    if composite > 0:
        sector_views = SectorThemeViews(
            overweight=["Banks", "Capital Goods", "Industrials", "Auto"],
            underweight=["Pure defensives"],
        )
    elif composite < 0:
        sector_views = SectorThemeViews(
            overweight=["Pharma", "FMCG", "Quality private banks"],
            underweight=["High-beta cyclicals", "Speculative small caps"],
        )
    else:
        sector_views = SectorThemeViews()

    warnings: list[str] = []
    if snap["blocks"]["valuation"]["score"] <= -2:
        warnings.append("Valuation rich — anti-chase active. Equity tilt capped at 0.")
    if composite == 0:
        warnings.append("Tactical regime Neutral — recommendation tracks strategic anchor.")

    eq_delta = recommended_allocation.equity - strategic["equity"]
    rebal: list[str] = []
    if eq_delta > 0:
        rebal.append(f"Tilt +{eq_delta}pp into equity vs. strategic.")
    elif eq_delta < 0:
        rebal.append(f"Trim {abs(eq_delta)}pp from equity vs. strategic.")

    return AllocationOutput(
        investor_risk_band=band,
        strategic_allocation=AllocationBuckets(**strategic),
        strategic_equity_split=EquitySplit(**equity_split),
        tactical_regime_score=composite,
        tactical_regime_label=regime_label,
        signal_breakdown={
            k: SignalEntry(score=v["score"], reason=v["reason"]) for k, v in snap["blocks"].items()
        },
        recommended_allocation=recommended_allocation,
        recommended_equity_split=recommended_equity_split,
        debt_duration_stance=debt_duration_stance,  # type: ignore[arg-type]
        sector_theme_views=sector_views,
        rebalancing_actions=rebal,
        warnings=warnings,
    )
