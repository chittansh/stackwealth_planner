"""
Tax harvesting — port of skills/tax/index.ts.
"""
from __future__ import annotations

from typing import Any

from ..db import get_plan
from ..types import GainHarvest, LossHarvest, PlanState, TaxView

LTCG_HEADROOM_INR = 125_000
LTCG_RATE = 0.125
STCG_RATE = 0.20
ROUND_TRIP_COST_PCT = 0.005
UNREALIZED_GAIN_PROXY = 0.30


async def harvest(args: dict[str, Any]) -> dict | TaxView:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    if not plan.computed.risk_profile or not plan.computed.risk_profile.recommended_score:
        return {"error": "risk_gate_required"}
    return compute_tax(plan)


def compute_tax(plan: PlanState) -> TaxView:
    realized_ltcg_fy = 0
    realized_stcg_fy = 0
    headroom_remaining = max(0, LTCG_HEADROOM_INR - realized_ltcg_fy)

    candidates: list[dict] = []
    for h in plan.mutual_funds:
        cur = h.current_value or 0
        if cur > 0:
            candidates.append(
                {"id": h.id, "cur": cur, "gain": cur * UNREALIZED_GAIN_PROXY, "kind": "mf", "trading": False}
            )
    for h in plan.equity_stocks:
        cur = h.current_value or 0
        if cur > 0:
            candidates.append(
                {
                    "id": h.id,
                    "cur": cur,
                    "gain": cur * UNREALIZED_GAIN_PROXY,
                    "kind": "stock",
                    "trading": h.long_term_or_trading == "trading",
                }
            )

    gain_harvest_suggestions: list[GainHarvest] = []
    remaining = headroom_remaining
    for c in sorted(candidates, key=lambda x: -x["gain"]):
        if remaining <= 0:
            break
        sell_gain = min(c["gain"], remaining)
        fraction = sell_gain / c["gain"] if c["gain"] > 0 else 0
        if fraction <= 0.001:
            continue
        sell_value = c["cur"] * fraction
        tax_saved = sell_gain * LTCG_RATE
        churn = sell_value * ROUND_TRIP_COST_PCT
        if tax_saved <= churn:
            continue
        gain_harvest_suggestions.append(
            GainHarvest(
                holding_id=c["id"],
                units=fraction * 100,
                expected_gain=round(sell_gain),
                tax_saved=round(tax_saved),
            )
        )
        remaining -= sell_gain

    loss_harvest_suggestions: list[LossHarvest] = []
    for c in candidates:
        if not c["trading"]:
            continue
        loss_proxy = c["cur"] * 0.10
        offset = loss_proxy * STCG_RATE
        churn = c["cur"] * ROUND_TRIP_COST_PCT
        if offset <= churn:
            continue
        loss_harvest_suggestions.append(
            LossHarvest(
                holding_id=c["id"],
                units=100,
                expected_loss=-round(loss_proxy),
                tax_offset=round(offset),
            )
        )

    fee_warnings: list[str] = []
    if not gain_harvest_suggestions and headroom_remaining > 0:
        fee_warnings.append("No gain-harvest opportunities cleared the round-trip cost gate this FY.")

    net_post = sum(s.tax_saved for s in gain_harvest_suggestions) + sum(
        s.tax_offset for s in loss_harvest_suggestions
    )

    return TaxView(
        ltcg_headroom_remaining=headroom_remaining,
        realized_ltcg_fy=realized_ltcg_fy,
        realized_stcg_fy=realized_stcg_fy,
        gain_harvest_suggestions=gain_harvest_suggestions,
        loss_harvest_suggestions=loss_harvest_suggestions,
        fee_vs_value_warnings=fee_warnings,
        net_post_tax_delta=net_post,
    )
