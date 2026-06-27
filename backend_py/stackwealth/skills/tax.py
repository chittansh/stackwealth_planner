"""
Tax harvesting — port of skills/tax/index.ts.
"""
from __future__ import annotations

from typing import Any

from ..db import get_plan
from ..tracing import traced_calc
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


@traced_calc("calc.tax")
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


# ─────────────────────────────────────────────────────────────────────────
# Old vs New regime comparison — Excel `Tax Comparison` tab
# FY 2025-26 / AY 2026-27 slabs.
# ─────────────────────────────────────────────────────────────────────────

CESS_RATE = 0.04

NEW_REGIME_SLABS = [
    (400_000, 0.00),
    (800_000, 0.05),
    (1_200_000, 0.10),
    (1_600_000, 0.15),
    (2_000_000, 0.20),
    (2_400_000, 0.25),
    (float("inf"), 0.30),
]
NEW_REGIME_STANDARD_DEDUCTION = 75_000
NEW_REGIME_REBATE_THRESHOLD = 1_200_000

OLD_REGIME_SLABS = [
    (250_000, 0.00),
    (500_000, 0.05),
    (1_000_000, 0.20),
    (float("inf"), 0.30),
]
OLD_REGIME_STANDARD_DEDUCTION = 50_000
OLD_REGIME_REBATE_THRESHOLD = 500_000

DEDUCTION_LIMITS = {
    "80C":         150_000,
    "80CCD_1B":     50_000,
    "80D_self":     25_000,
    "80D_parents":  50_000,
    "24b":         200_000,
}


def _slab_tax(income: float, slabs: list[tuple[float, float]]) -> float:
    """Walk slabs bottom-up — same as Excel SUMPRODUCT slab formula."""
    tax = 0.0
    prev = 0.0
    for upper, rate in slabs:
        if income <= prev:
            break
        chunk = min(income, upper) - prev
        tax += chunk * rate
        prev = upper
    return tax


def _apply_87A_rebate(income: float, tax: float, threshold: float) -> float:
    return 0.0 if income <= threshold else tax


def compute_tax_regime_comparison(plan: PlanState) -> dict:
    """Excel `Tax Comparison` — compute liability under both regimes,
    factoring 80C / 80CCD(1B) / 80D / 24(b) / HRA on the old regime side.
    Returns the lower-tax recommendation and the savings delta."""
    fsi = plan.freedom_score_inputs
    monthly_income = fsi.monthly_income or 0
    annual_gross = monthly_income * 12

    # rental + business income are reported in the regime view but already
    # part of fsi.monthly_income — kept here for downstream consumers.
    income_block = plan.income_details
    rental_pa = 0
    business_pa = 0
    if income_block:
        rental_pa = ((income_block.client_rental_income or 0)
                     + (income_block.spouse_rental_income or 0)) * 12
        business_pa = ((income_block.client_business_income or 0)
                       + (income_block.spouse_business_income or 0)) * 12

    # 80C — PPF + RD + insurance premium (life) + mutual_fund_sip if ELSS-tagged.
    # We don't yet tag MFs as ELSS, so MF SIP is excluded conservatively.
    mi = plan.monthly_investments
    contrib_80C = 0.0
    if mi:
        contrib_80C = (
            (mi.ppf or 0) * 12 +
            (mi.rd or 0) * 12 +
            (mi.insurance_premium or 0) * 12
        )
    sec_80C_utilised = min(DEDUCTION_LIMITS["80C"], contrib_80C)

    # 80CCD(1B) — NPS top-up (₹50K)
    sec_80CCD1B = min(
        DEDUCTION_LIMITS["80CCD_1B"],
        ((mi.nps or 0) * 12) if mi and mi.nps is not None else 0,
    )

    # 80D — health premiums (self + parents up to ₹75K combined)
    health_premium = 0.0
    if plan.insurance_details:
        if plan.insurance_details.health_insurance:
            health_premium += plan.insurance_details.health_insurance.annual_premium or 0
        if plan.insurance_details.family_floater:
            health_premium += plan.insurance_details.family_floater.annual_premium or 0
    sec_80D = min(
        DEDUCTION_LIMITS["80D_self"] + DEDUCTION_LIMITS["80D_parents"],
        health_premium,
    )

    # 24(b) — home-loan interest (use loan EMI * interest fraction proxy)
    home = plan.loans_liabilities.home_loan if plan.loans_liabilities else None
    home_interest_pa = 0
    if home and (home.outstanding_amount or 0) > 0:
        rate = (home.interest_rate or 8.5) / 100
        home_interest_pa = min(
            DEDUCTION_LIMITS["24b"],
            (home.outstanding_amount or 0) * rate,
        )
    sec_24b = home_interest_pa

    # HRA — not modelled directly here (needs basic salary split + city + rent).
    # Excel leaves HRA as a user-entered override; we follow the same convention.
    hra = 0

    total_deductions_old = (
        sec_80C_utilised + sec_80CCD1B + sec_80D + sec_24b + hra
    )

    # --- Old regime ---
    taxable_old = max(0, annual_gross - OLD_REGIME_STANDARD_DEDUCTION - total_deductions_old)
    tax_old = _slab_tax(taxable_old, OLD_REGIME_SLABS)
    tax_old = _apply_87A_rebate(taxable_old, tax_old, OLD_REGIME_REBATE_THRESHOLD)
    tax_old_cess = tax_old * CESS_RATE
    final_old = tax_old + tax_old_cess

    # --- New regime ---
    taxable_new = max(0, annual_gross - NEW_REGIME_STANDARD_DEDUCTION)
    tax_new = _slab_tax(taxable_new, NEW_REGIME_SLABS)
    tax_new = _apply_87A_rebate(taxable_new, tax_new, NEW_REGIME_REBATE_THRESHOLD)
    tax_new_cess = tax_new * CESS_RATE
    final_new = tax_new + tax_new_cess

    recommended = "new" if final_new <= final_old else "old"
    savings = abs(final_new - final_old)

    return {
        "fy": "2025-26",
        "annual_gross_income": round(annual_gross),
        "old_regime": {
            "standard_deduction": OLD_REGIME_STANDARD_DEDUCTION,
            "deductions": {
                "80C": round(sec_80C_utilised),
                "80CCD_1B": round(sec_80CCD1B),
                "80D": round(sec_80D),
                "24b": round(sec_24b),
                "HRA": round(hra),
                "total": round(total_deductions_old),
            },
            "taxable_income": round(taxable_old),
            "tax_before_cess": round(tax_old),
            "cess": round(tax_old_cess),
            "total_tax": round(final_old),
            "effective_rate": round(final_old / annual_gross, 4) if annual_gross else 0,
        },
        "new_regime": {
            "standard_deduction": NEW_REGIME_STANDARD_DEDUCTION,
            "taxable_income": round(taxable_new),
            "tax_before_cess": round(tax_new),
            "cess": round(tax_new_cess),
            "total_tax": round(final_new),
            "effective_rate": round(final_new / annual_gross, 4) if annual_gross else 0,
        },
        "recommended_regime": recommended,
        "annual_savings_with_recommended": round(savings),
        "rationale": (
            f"Old regime saves ₹{round(savings):,} via 80C/80D/24(b) deductions"
            if recommended == "old"
            else f"New regime saves ₹{round(savings):,} — current deductions don't outweigh the wider slabs"
        ),
    }


async def regime_comparison(args: dict[str, Any]) -> dict:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    return compute_tax_regime_comparison(plan)
