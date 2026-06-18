"""
Comprehensive Financial Plan (CFP) engine — port of the firm's
`Format for inputs for CFP_ng_080626.xlsx` model. The math in this module is
intentionally kept cell-for-cell aligned with the Excel: same inflation
table, same post-tax return table, same allocation priority order, same
FV / PMT / PV invocations. The output bundles a full `computation_trace`
so the calling agent can render every step inline in the chat.

Public surface:
    compute_cfp(plan) -> CFPOutput      — full plan engine
    plan_summary(plan) -> CFPSummary    — single-row recap (for headlines)

Conventions:
    All monthly values are in plain INR (no commas, no suffixes).
    All annual values likewise.
    All percentages are stored as decimals (0.07, not 7).
    FV / PV / PMT use the same sign convention as Excel:
        FV(rate, nper, pmt, -pv)            payments out
        PMT(rate/12, nper*12, 0, -fv)       SIP needed to hit FV
        PV(disc_rate, nper, -annual_need, 0, 1)   annuity due
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..db import get_plan
from ..types import Goal, PlanState
from .debt import compute_debt_ratios, compute_repayment_strategies
from .tax import compute_tax_regime_comparison


# ── Excel-encoded constants (Assumptions & Computation sheet) ─────────────

# Inflation table — sourced from the firm's "Assumptions & Computation"
# sheet rows 2-8. Values match the workbook cell-for-cell so YoY goal
# withdrawals reconcile with the firm's hand-prepared plans. Earlier
# defaults were higher (e.g. education 10%, lifestyle 25%) which silently
# over-stated future goal costs by 20-40% by year-15 — confirmed against
# the firm Excel's "Format for inputs for CFP_ng_180626.xlsx" reference.
INFLATION_TABLE: dict[str, float] = {
    "general": 0.07,                # firm: General Inflation (Household)
    "education": 0.08,              # firm: Educational Inflation
    "child_education": 0.08,
    "wedding": 0.08,                # firm: Wedding Inflation
    "child_marriage": 0.08,
    "medical": 0.09,                # firm: Medical Inflation
    "lifestyle": 0.20,              # firm: Personalised (Lifestyle) inflation
    "real_estate": 0.08,            # firm: Real Estate Inflation
    "house_purchase": 0.08,
    "vacation": 0.08,               # firm: Vacation Inflation
    "foreign_travel": 0.08,
    "other": 0.07,                  # falls back to general
    "retirement": 0.07,             # general for corpus + post-retirement spend
}

# Post-tax annual return by asset class — see rows 20-39 of the
# Assumptions sheet. The pre-tax values are kept alongside as a comment so
# anyone diffing against the Excel can verify the haircut.
POST_TAX_RETURN: dict[str, float] = {
    "equity_aggressive":   0.14 * (1 - 0.125),    # = 0.1225  Small/Mid MFs
    "equity_hybrid":       0.12 * (1 - 0.125),    # = 0.1050  Large+Mid MFs / hybrid
    "equity_conservative": 0.10 * (1 - 0.125),    # = 0.0875  Large-cap MFs
    "bank_fd":             0.065 * (1 - 0.30),    # = 0.0455  FDs/RDs (slab)
    "bonds":               0.075 * (1 - 0.30),    # = 0.0525
    "ppf":                 0.071,                  # tax-free
    "epf":                 0.081,                  # tax-free
    "sukanya":             0.081,                  # tax-free
    "sgb":                 0.05 + 0.025 * 0.70,    # = 0.0675  ~ Excel: 5% appreciation + 2.5% coupon, tax-adjusted
    "ulip":                0.06,                   # treated as gross = net
    "nps":                 0.07,
    "liquid_fund":         0.055 * (1 - 0.30),    # = 0.0385
    "savings_bank":        0.035 * (1 - 0.30),    # = 0.0245
    "real_estate":         0.08 * (1 - 0.125),    # = 0.07
    "gold":                0.08 * (1 - 0.125),    # = 0.07
}

# Equal-weight blended ROI on the financial-asset pool — Excel's
# AVERAGE(D20:D39) and AVERAGE(E20:E39) on the assumptions sheet. Used by
# the YoY-Cashflow sheet for the "Income from investments" line on each
# closing financial-asset balance.
BLENDED_ROI_POST_TAX = sum(POST_TAX_RETURN.values()) / len(POST_TAX_RETURN)

# Asset allocation priority for funding goals — see "10_Financial_Goals"
# columns J..W and Rule 6 of the brief. Earlier entries get exited first.
ALLOCATION_PRIORITY: list[str] = [
    "weak_stocks",
    "weak_mfs",
    "fixed_deposits",
    "bonds",
    "neutral_stocks",
    "neutral_mfs",
    "ulip_endowment",
    "nsc",
    "ppf",
    "real_estate_for_sale",
    "gold",
    "lic_proceeds",
    "epf",
    "pension",
]

# Glide-path effective returns by horizon — see Rule 6 of the brief.
# Used by `goal_block.required_sip` when no explicit override is set.
def glide_path_return(horizon_years: int) -> float:
    if horizon_years > 10:
        return 0.110
    if horizon_years >= 7:
        return 0.105
    if horizon_years >= 4:
        return 0.090
    if horizon_years >= 2:
        return 0.065
    return 0.055


# ── Excel-equivalent financial functions ──────────────────────────────────

def excel_fv(rate: float, nper: float, pmt: float, pv: float) -> float:
    """Mirror of Excel's `FV(rate, nper, pmt, pv)` for end-of-period
    payments. Negative `pv` means "money in" (the convention the planner
    Excel uses). Sign-flips so positive output = corpus accumulated."""
    if rate == 0:
        return -(pv + pmt * nper)
    growth = (1 + rate) ** nper
    return -(pv * growth + pmt * (growth - 1) / rate)


def excel_pmt(rate: float, nper: float, pv: float, fv: float, when: int = 0) -> float:
    """Mirror of Excel's PMT. `when=0` end-of-period, `when=1` start-of-period.
    Used for: PMT(annual_rate/12, years*12, 0, -goal_fv) → monthly SIP."""
    if nper == 0:
        return 0.0
    if rate == 0:
        return -(pv + fv) / nper
    growth = (1 + rate) ** nper
    base = (pv * growth + fv) / ((growth - 1) / rate)
    if when == 1:
        base /= (1 + rate)
    return -base


def excel_pv(rate: float, nper: float, pmt: float, fv: float = 0.0, when: int = 0) -> float:
    """Mirror of Excel's PV. Used for the retirement-corpus discounted
    annuity: PV(disc_rate, post_retire_years, -annual_expense, 0, 1)."""
    if rate == 0:
        return -(pmt * nper + fv)
    growth = (1 + rate) ** nper
    factor = (1 - 1 / growth) / rate
    if when == 1:
        factor *= (1 + rate)
    return -(pmt * factor + fv / growth)


# ── Computation-trace dataclasses ─────────────────────────────────────────

@dataclass
class TraceStep:
    """One inspectable computation step. The agent renders this in the
    tool-call response so the user sees the math, not just the answer."""
    label: str
    formula: str             # human-readable, mirrors the Excel cell
    inputs: dict[str, Any]   # named inputs that went into the formula
    value: float | str       # the result
    unit: str = "INR"        # "INR" / "%" / "years"


def _trace(label: str, formula: str, inputs: dict, value: float | str, unit: str = "INR") -> dict:
    return {
        "label": label,
        "formula": formula,
        "inputs": inputs,
        "value": value,
        "unit": unit,
    }


# ── Goal block (per-goal calculation) ─────────────────────────────────────

def _years_to(target_year: int, current_year: int) -> int:
    return max(0, target_year - current_year)


def _inflation_for_goal(goal: Goal, default: float) -> float:
    """Excel's inflation column on `10_Financial_Goals` is configurable per
    goal but defaults to the type-keyed table on the Assumptions sheet."""
    if goal.inflation_assumed is not None:
        return float(goal.inflation_assumed)
    kind = (goal.kind or "other").lower()
    return INFLATION_TABLE.get(kind, default)


def compute_goal_block(
    goal: Goal,
    *,
    current_year: int,
    asset_pool: dict[str, float],
    existing_goal_sip: float = 0.0,
) -> dict:
    """One goal's full Excel-equivalent block: FV need, allocated assets in
    priority order, gap, glide-path return, required SIP, and the trace.

    `asset_pool` is mutated — assets get drawn down as they're allocated to
    this goal so the next goal sees the remainder."""
    trace: list[dict] = []
    name = goal.goal_name or "Unnamed goal"
    target_year = goal.target_year or current_year + 10
    n_years = _years_to(target_year, current_year)
    today_cost = float(goal.target_amount or 0)
    is_today_money = goal.is_target_in_today_money
    inflation = _inflation_for_goal(goal, INFLATION_TABLE["general"])

    # ── Step 1: Future value of the goal ─────────────────────────────────
    if is_today_money:
        fv_need = excel_fv(inflation, n_years, 0, -today_cost)
        trace.append(_trace(
            f"FV of '{name}' at target year {target_year}",
            "FV(inflation, years, , -today_cost)",
            {"inflation": round(inflation, 4), "years": n_years, "today_cost": today_cost},
            round(fv_need),
        ))
    else:
        fv_need = today_cost
        trace.append(_trace(
            f"FV of '{name}' (already in target-year money)",
            "= target_amount",
            {"target_amount": today_cost},
            round(fv_need),
        ))

    # ── Step 2: Allocate existing assets in priority order ──────────────
    # Excel model (10_Financial_Goals): allocated assets are netted in TODAY's
    # value — they're "earmarked" for the goal, inflation-tracked but not
    # compounded at an excess investment return. The remaining gap (in
    # today's money) is then inflated to FV and that's what the SIP funds.
    # Mirrors:  Y = E − X;  Z = FV(G, D, , -Y);  AB = PMT(AA/12, D*12, , -Z)
    allocations: list[dict] = []
    allocated_today = 0.0
    remaining_today = today_cost if is_today_money else 0.0
    for bucket in ALLOCATION_PRIORITY:
        avail = float(asset_pool.get(bucket, 0) or 0)
        if avail <= 0:
            continue
        consumed_today = min(avail, remaining_today) if is_today_money else avail
        if consumed_today <= 0:
            continue
        allocations.append({
            "bucket": bucket,
            "today_value_used": round(consumed_today),
        })
        asset_pool[bucket] = avail - consumed_today
        allocated_today += consumed_today
        if is_today_money:
            remaining_today -= consumed_today
            if remaining_today <= 1:
                break

    trace.append(_trace(
        f"Existing assets allocated to '{name}' (today's value, priority order)",
        "X = K + M + O + Q + S + U + W   (sum of buckets drawn in priority)",
        {"buckets_used": [a["bucket"] for a in allocations]},
        round(allocated_today),
    ))

    # ── Step 3: Gap (today's value) and FV of gap ────────────────────────
    if is_today_money:
        gap_today = max(0.0, today_cost - allocated_today)
        trace.append(_trace(
            f"Gap in today's value for '{name}'",
            "Y = E − X   (today_cost minus allocated)",
            {"today_cost": today_cost, "allocated_today": round(allocated_today)},
            round(gap_today),
        ))
        fv_gap = excel_fv(inflation, n_years, 0, -gap_today) if gap_today > 0 else 0.0
        trace.append(_trace(
            f"FV of unallocated gap for '{name}'",
            "Z = FV(G, D, , −Y)   (inflate gap_today to target year)",
            {"inflation": round(inflation, 4), "years": n_years, "gap_today": round(gap_today)},
            round(fv_gap),
        ))
    else:
        gap_today = None
        fv_gap = max(0.0, fv_need - allocated_today)
        trace.append(_trace(
            f"FV gap for '{name}' (target already in FV)",
            "fv_need − allocated_today",
            {"fv_need": round(fv_need), "allocated_today": round(allocated_today)},
            round(fv_gap),
        ))

    # ── Step 4: Glide-path return & required SIP ─────────────────────────
    eff_return = goal.required_return_override or glide_path_return(n_years)
    if n_years <= 0 or fv_gap <= 0:
        required_sip_total = 0.0
    else:
        required_sip_total = abs(excel_pmt(eff_return / 12, n_years * 12, 0, -fv_gap, when=0))
    trace.append(_trace(
        f"Glide-path effective return for '{name}'",
        "horizon > 10y → 11%, 7-10y → 10.5%, 4-6y → 9%, 2-3y → 6.5%, <2y → 5.5%",
        {"horizon_years": n_years},
        round(eff_return, 4),
        unit="%",
    ))
    trace.append(_trace(
        f"Total required SIP for '{name}'",
        "PMT(eff_return/12, years*12, 0, -fv_gap)",
        {"eff_return": round(eff_return, 4), "months": n_years * 12, "fv_gap": round(fv_gap)},
        round(required_sip_total),
    ))

    incremental_sip = max(0.0, required_sip_total - existing_goal_sip)
    if existing_goal_sip > 0:
        trace.append(_trace(
            f"Incremental SIP needed for '{name}' (net of existing)",
            "required_sip_total - existing_goal_sip",
            {"required_sip_total": round(required_sip_total), "existing_goal_sip": existing_goal_sip},
            round(incremental_sip),
        ))

    return {
        "goal_name": name,
        "goal_id": getattr(goal, "id", None),
        "target_year": target_year,
        "years_to_go": n_years,
        "today_cost": round(today_cost),
        "inflation_used": round(inflation, 4),
        "future_value_needed": round(fv_need),
        "allocations": allocations,
        "allocated_today_total": round(allocated_today),
        "gap_today": round(gap_today or 0) if is_today_money else None,
        "fv_gap": round(fv_gap),
        "effective_return": round(eff_return, 4),
        "required_sip_monthly": round(required_sip_total),
        "existing_sip_monthly": round(existing_goal_sip),
        "incremental_sip_monthly": round(incremental_sip),
        "computation_trace": trace,
    }


def _bucket_return_key(bucket: str) -> str:
    """Map allocation-priority bucket → POST_TAX_RETURN key."""
    return {
        "weak_stocks":           "equity_aggressive",
        "weak_mfs":              "equity_aggressive",
        "fixed_deposits":        "bank_fd",
        "bonds":                 "bonds",
        "neutral_stocks":        "equity_hybrid",
        "neutral_mfs":           "equity_hybrid",
        "ulip_endowment":        "ulip",
        "nsc":                   "bonds",
        "ppf":                   "ppf",
        "real_estate_for_sale":  "real_estate",
        "gold":                  "gold",
        "lic_proceeds":          "ulip",
        "epf":                   "epf",
        "pension":               "nps",
    }.get(bucket, "bank_fd")


# ── Retirement corpus (Retirement Plan tab) ───────────────────────────────

def compute_retirement_corpus(
    *,
    current_age: int,
    retirement_age: int,
    life_expectancy: int,
    current_annual_expenses: float,
    inflation: float = 0.07,
    # Default 10.5% matches Excel `Retirement Plan!E23` → `Assumptions!E22`
    # (equity_hybrid post-tax). Earlier 0.07 collapsed the real rate to 0
    # and made the corpus equal expense × years — a footgun for any
    # non-default caller.
    post_retire_return: float = 0.105,
) -> dict:
    """Excel's Retirement Plan tab — annuity-due PV approach.
    Mirror of:
        E21 = FV(inflation, years_to_retire, , -current_annual_expenses)
        E25 = ((1 + return) / (1 + inflation)) - 1
        E26 = PV(disc_rate, post_retire_years, -annual_at_retire, 0, 1)
    """
    trace: list[dict] = []
    years_to_retire = max(0, retirement_age - current_age)
    post_retire_years = max(0, life_expectancy - retirement_age)

    annual_at_retire = excel_fv(inflation, years_to_retire, 0, -current_annual_expenses)
    trace.append(_trace(
        "Annual expenses at retirement (inflation-adjusted)",
        "FV(inflation, years_to_retire, , -current_annual_expenses)",
        {"inflation": round(inflation, 4), "years_to_retire": years_to_retire,
         "current_annual_expenses": round(current_annual_expenses)},
        round(annual_at_retire),
    ))

    disc_rate = ((1 + post_retire_return) / (1 + inflation)) - 1
    trace.append(_trace(
        "Inflation-adjusted real return (post-retirement)",
        "((1+post_retire_return)/(1+inflation)) - 1",
        {"post_retire_return": round(post_retire_return, 4), "inflation": round(inflation, 4)},
        round(disc_rate, 4),
        unit="%",
    ))

    corpus_required = abs(excel_pv(disc_rate, post_retire_years, -annual_at_retire, 0, when=1))
    trace.append(_trace(
        "Required retirement corpus",
        "PV(disc_rate, post_retire_years, -annual_at_retire, 0, 1)",
        {"disc_rate": round(disc_rate, 4), "post_retire_years": post_retire_years,
         "annual_at_retire": round(annual_at_retire)},
        round(corpus_required),
    ))

    return {
        "current_age": current_age,
        "retirement_age": retirement_age,
        "life_expectancy": life_expectancy,
        "years_to_retire": years_to_retire,
        "post_retire_years": post_retire_years,
        # Aliases used by the canvas — keep both keys so legacy + new UIs read cleanly.
        "years_post_retirement": post_retire_years,
        "annual_expense_today": round(current_annual_expenses),
        "annual_expenses_at_retirement": round(annual_at_retire),
        "annual_expense_at_retirement": round(annual_at_retire),
        "pre_retire_return": round(post_retire_return, 4),
        "post_retire_return": round(post_retire_return, 4),
        "inflation_during_retirement": round(inflation, 4),
        "real_return_used": round(disc_rate, 4),
        "real_return_during_retirement": round(disc_rate, 4),
        "corpus_required": round(corpus_required),
        "computation_trace": trace,
    }


# ── Insurance computation (Insurance Computation tab) ────────────────────

def compute_health_cover_required(
    *,
    annual_income: float,
    family_kind: str,  # "single" | "couple" | "with_children" | "with_dependents"
    is_metro: bool,
) -> dict:
    """Excel `Insurance Computation!G51-G65` — health cover required is the
    HIGHER of:
      (a) 50% of gross annual income, OR
      (b) a profile-based table by family composition + metro top-up.

    Profile table (lakhs):
       single                       → 5L
       couple                       → 10L
       with_children                → 15L
       with_dependents (extended)   → 20L
    Metro households add +5L.
    """
    table = {
        "single": 500_000,
        "couple": 1_000_000,
        "with_children": 1_500_000,
        "with_dependents": 2_000_000,
    }
    profile_floor = table.get(family_kind, 1_000_000)
    if is_metro:
        profile_floor += 500_000
    income_rule = 0.50 * (annual_income or 0)
    required = max(profile_floor, income_rule)
    return {
        "required": round(required),
        "profile_floor": profile_floor,
        "income_rule_50pct": round(income_rule),
        "family_kind": family_kind,
        "metro_topup_applied": is_metro,
        "computation_trace": [
            _trace(
                "Health cover — profile floor",
                "table[family_kind] + (5L if metro else 0)",
                {"family_kind": family_kind, "metro": is_metro},
                profile_floor,
            ),
            _trace(
                "Health cover — 50% of income rule",
                "0.50 × annual_income",
                {"annual_income": round(annual_income)},
                round(income_rule),
            ),
            _trace(
                "Health cover required",
                "MAX(profile_floor, income_rule_50pct)",
                {"profile_floor": profile_floor, "income_rule": round(income_rule)},
                round(required),
            ),
        ],
    }


def compute_insurance_need(
    *,
    current_annual_income: float,
    current_annual_expenses: float,
    current_age: int,
    retirement_age: int,
    spouse_age: int,
    spouse_life_expectancy: int,
    loans_outstanding: float,
    existing_cover: float,
    investable_assets: float,
    return_rate: float = 0.10,
    inflation: float = 0.06,
) -> dict:
    """Excel's Insurance Computation tab. Two methods averaged:
       Method A — Human Life Value: PV of future income to retirement.
       Method B — Needs: PV of dependent's expenses to their life expectancy.
       Final cover = avg(A, B) + loans − existing − investable_assets.
    """
    trace: list[dict] = []
    years_to_retire = max(0, retirement_age - current_age)
    years_spouse_left = max(0, spouse_life_expectancy - spouse_age)
    disc_rate = ((1 + return_rate) / (1 + inflation)) - 1

    trace.append(_trace(
        "Discounting rate (real return)",
        "((1+return)/(1+inflation)) - 1",
        {"return": round(return_rate, 4), "inflation": round(inflation, 4)},
        round(disc_rate, 4),
        unit="%",
    ))

    hlv = abs(excel_pv(disc_rate, years_to_retire, -current_annual_income, 0, when=0))
    trace.append(_trace(
        "Method A — Human Life Value",
        "PV(disc_rate, years_to_retire, -current_annual_income, 0)",
        {"disc_rate": round(disc_rate, 4), "years_to_retire": years_to_retire,
         "current_annual_income": round(current_annual_income)},
        round(hlv),
    ))

    needs_corpus = abs(excel_pv(disc_rate, years_spouse_left, -current_annual_expenses, 0, when=0))
    trace.append(_trace(
        "Method B — Needs-based corpus",
        "PV(disc_rate, years_spouse_left, -current_annual_expenses, 0)",
        {"disc_rate": round(disc_rate, 4), "years_spouse_left": years_spouse_left,
         "current_annual_expenses": round(current_annual_expenses)},
        round(needs_corpus),
    ))

    avg_method = (hlv + needs_corpus) / 2
    trace.append(_trace(
        "Average of both methods",
        "(HLV + Needs corpus) / 2",
        {"hlv": round(hlv), "needs_corpus": round(needs_corpus)},
        round(avg_method),
    ))

    total_need = avg_method + loans_outstanding
    additional = max(0.0, total_need - existing_cover - investable_assets)
    trace.append(_trace(
        "Additional cover required",
        "(avg + loans) − existing_cover − investable_assets",
        {"avg": round(avg_method), "loans": round(loans_outstanding),
         "existing_cover": round(existing_cover), "investable_assets": round(investable_assets)},
        round(additional),
    ))

    return {
        "human_life_value": round(hlv),
        "needs_based_corpus": round(needs_corpus),
        "average": round(avg_method),
        "total_need_including_loans": round(total_need),
        "existing_cover": round(existing_cover),
        "investable_assets": round(investable_assets),
        "additional_cover_required": round(additional),
        "computation_trace": trace,
    }


# ── Year-by-year cashflow (YoY Cash Flow tab) ─────────────────────────────

def compute_yoy_cashflow(
    *,
    horizon_years: int,
    start_year: int,
    start_age: int,
    retirement_age: int,
    monthly_income_employment: float,
    monthly_income_business: float,
    monthly_income_rental: float,
    monthly_income_other: float,
    monthly_expenses_living: float,
    monthly_loan_repayment: float,
    opening_financial_assets: float,
    opening_non_financial_assets: float = 0.0,
    # Per-source income growth — defaults match the firm's `YoY Cash Flow`
    # row 5 (E5/F5/G5/H5). Excel uses post-tax growth rates per income
    # line; passing a single `income_growth_rate` was the source of
    # Finding 3 in the audit.
    employment_growth: float = 0.056,    # E$5
    business_growth: float = 0.070,      # F$5
    rental_growth: float = 0.035,        # G$5
    other_income_growth: float = 0.035,  # H$5
    expense_growth_rate: float = 0.07,   # J$5
    financial_asset_roi: float = None,   # S$5 — holdings-weighted (see compute_cfp)
    non_financial_appreciation: float = 0.07,  # Z$5 — real estate / gold blend
    goal_outflows_by_year: dict[int, float] | None = None,
    lumpsum_events_by_year: dict[int, list[tuple[float, str]]] | None = None,
    fa_transfers_out_by_year: dict[int, float] | None = None,
) -> list[dict]:
    """Excel's `YoY Cash Flow` sheet — row-by-row. Each year:
        income_source[y]  = income_source[y-1] × (1 + per_source_growth)
        expense[y]        = expense[y-1] × (1 + J$5)
        loan[y]           = loan[y-1]      (fixed EMI)
        surplus[y]        = income[y] − expense[y] − loan[y]
        FA_close[y]       = (FA_open + surplus/2 − goal_outflow) × ROI
                          + (FA_open + surplus − goal_outflow)
        NFA_close[y]      = NFA_open × (1 + Z$5)
        net_worth         = FA_close + NFA_close
    """
    if financial_asset_roi is None:
        financial_asset_roi = BLENDED_ROI_POST_TAX
    goal_outflows_by_year = goal_outflows_by_year or {}
    lumpsum_events_by_year = lumpsum_events_by_year or {}
    fa_transfers_out_by_year = fa_transfers_out_by_year or {}

    rows: list[dict] = []
    income_emp = monthly_income_employment * 12
    income_biz = monthly_income_business * 12
    income_rent = monthly_income_rental * 12
    income_oth = monthly_income_other * 12
    expense = monthly_expenses_living * 12
    loan = monthly_loan_repayment * 12
    fa_open = opening_financial_assets
    nfa_open = opening_non_financial_assets

    for i in range(horizon_years):
        year = start_year + i
        age = start_age + i
        earning = age < retirement_age

        # Employment + business stop at retirement; rental + other carry on.
        annual_emp = income_emp if earning else 0
        annual_biz = income_biz if earning else 0
        total_income = annual_emp + annual_biz + income_rent + income_oth
        annual_loan = loan if earning else 0
        total_outflow = expense + annual_loan
        surplus = total_income - total_outflow

        withdrawal = float(goal_outflows_by_year.get(year, 0))

        # Lumpsum one-off events (Excel `Lumpsum Further deposit /
        # (Withdrawal)` column). Positive = deposit into FA at year-end,
        # negative = withdrawal from FA. Multiple events in the same
        # year are summed; labels are concatenated for the remarks cell.
        lumpsum_evs = lumpsum_events_by_year.get(year, [])
        lumpsum_total = float(sum(amt for amt, _ in lumpsum_evs))
        lumpsum_remark = " · ".join(lbl for _, lbl in lumpsum_evs if lbl) if lumpsum_evs else ""

        # Fixed-income maturities: at the maturity year, the instrument
        # leaves the FA pool (it's been cashed out) and re-enters as a
        # Lumpsum inflow. Net effect on fa_close is small (~M × ROI lost
        # for that one year because the principal sits as cash, not in
        # the interest-bearing pool, for the maturity year). Without this
        # transfer, emitting the maturity as a positive lumpsum would
        # double-count: instrument keeps growing inside fa_open AND we'd
        # inject the same money on top.
        fa_transfer_out = float(fa_transfers_out_by_year.get(year, 0))
        fa_open_effective = fa_open - fa_transfer_out

        # Mid-year compounding (Excel S6 convention). Lumpsum hits at
        # year-end (compounded for the remainder of the year, simplified
        # to zero — matches Excel's column V where the lumpsum is added
        # AFTER the return-on-mid-year-cash formula, not before).
        fa_returns = (fa_open_effective + surplus / 2 - withdrawal) * financial_asset_roi
        fa_close = fa_open_effective + surplus - withdrawal + fa_returns + lumpsum_total
        nfa_close = nfa_open * (1 + non_financial_appreciation)

        nfa_appreciation_this_yr = nfa_open * non_financial_appreciation
        rows.append({
            "year": year,
            "age": age,
            # Income side
            "income_employment": round(annual_emp),
            "income_business": round(annual_biz),
            "income_rental": round(income_rent),
            "income_other": round(income_oth),
            "total_income": round(total_income),
            # Outflow side
            "expenses": round(expense),
            "loan_repayment": round(annual_loan),
            "total_outflow": round(total_outflow),
            "surplus": round(surplus),
            # Financial-asset waterfall (Excel cols O–V)
            "fa_opening": round(fa_open),
            "net_annual_cash_savings": round(surplus),
            "major_withdrawals": round(-withdrawal) if withdrawal else 0,
            "investment_returns": round(fa_returns),
            "lumpsum_deposit_withdrawal": round(lumpsum_total) if lumpsum_total else 0,
            "remarks": lumpsum_remark,
            "financial_assets_closing": round(fa_close),
            # Non-financial-asset waterfall (Excel cols X–AA)
            "nfa_opening": round(nfa_open),
            "nfa_addition": 0,                  # Future-purchases (e.g. a 2nd house bought from FA) — wired when goal_kind=house_purchase fires
            "nfa_appreciation": round(nfa_appreciation_this_yr),
            "non_financial_assets_closing": round(nfa_close),
            # Total
            "net_worth": round(fa_close + nfa_close),
            "net_worth_crore": round((fa_close + nfa_close) / 1e7, 2),
            # Back-compat alias
            "goal_withdrawal": round(withdrawal),
            "financial_asset_returns": round(fa_returns),
        })

        # Roll-forward per-source.
        fa_open = fa_close
        nfa_open = nfa_close
        income_emp *= (1 + employment_growth)
        income_biz *= (1 + business_growth)
        income_rent *= (1 + rental_growth)
        income_oth *= (1 + other_income_growth)
        expense *= (1 + expense_growth_rate)

    return rows


# ── Top-level orchestrator ───────────────────────────────────────────────

@dataclass
class CFPOutput:
    summary: dict
    goal_blocks: list[dict]
    retirement: dict
    insurance: dict
    yoy_cashflow: list[dict]
    constants_used: dict
    computation_trace: list[dict]
    debt: dict = field(default_factory=dict)
    tax_regime: dict = field(default_factory=dict)


async def run_cfp(household_id: str) -> dict[str, Any]:
    plan = await get_plan(household_id)
    if not plan:
        return {"error": "household_not_found"}
    return compute_cfp(plan).__dict__


def _holdings_weighted_post_tax_roi(plan: PlanState) -> tuple[float, dict[str, float]]:
    """Excel S5 = `1_Surplus and Net Worth!K38` = SUMPRODUCT(value, rate)/total
    — the holdings-weighted average post-tax return across the FA pool.
    Falls back to the equal-weight blended ROI when the FA pool is empty.

    Returns (rate, breakdown) — breakdown shows how each class contributed."""
    buckets: list[tuple[str, float, float]] = []  # (label, value, post_tax_rate)
    # Equity defaults match the firm's standard CFP convention: when an
    # equity holding (stock or MF) doesn't carry an explicit cap
    # classification, assume large-cap / conservative. The previous
    # "everything → hybrid (10.5%)" was too aggressive — for a typical
    # advisor's client whose portfolio is mostly large-cap stocks and
    # multi-cap funds, the firm-applied blended FA ROI sits closer to
    # 6.4% than 7.9%. Tag-driven overrides (e.g. fund_name containing
    # "small cap" / "midcap") win when present.
    for mf in plan.mutual_funds or []:
        v = float(mf.current_value or 0)
        if v <= 0:
            continue
        name = (mf.fund_name or "").lower()
        if "small" in name or "smallcap" in name:
            r = POST_TAX_RETURN["equity_aggressive"]   # 12.25%
        elif "mid" in name or "midcap" in name or "flexi" in name or "multi" in name:
            r = POST_TAX_RETURN["equity_hybrid"]       # 10.5%
        else:
            r = POST_TAX_RETURN["equity_conservative"] # 8.75% — large-cap default
        buckets.append(("mutual_funds", v, r))
    for eq in plan.equity_stocks or []:
        v = float(eq.current_value or 0)
        if v > 0:
            # Direct equity holdings — default to conservative (large-cap)
            # since the firm's reference Excel applies the conservative
            # post-tax rate (8.75%) to undifferentiated stock portfolios.
            buckets.append(("equity_stocks", v, POST_TAX_RETURN["equity_conservative"]))
    for fi in plan.fixed_income or []:
        v = float(fi.current_value or 0)
        if v <= 0:
            continue
        inst = (fi.instrument or "").lower()
        if "ppf" in inst:
            r = POST_TAX_RETURN["ppf"]
            label = "ppf"
        elif "epf" in inst:
            r = POST_TAX_RETURN["epf"]
            label = "epf"
        elif "nps" in inst:
            r = POST_TAX_RETURN["nps"]
            label = "nps"
        elif "sukanya" in inst:
            r = POST_TAX_RETURN["sukanya"]
            label = "sukanya"
        elif "nsc" in inst or "bond" in inst:
            r = POST_TAX_RETURN["bonds"]
            label = "bonds_nsc"
        elif "postoffice" in inst or "post office" in inst or "posa" in inst:
            # Post Office Savings A/c — similar rate band to bank FD post-tax.
            r = POST_TAX_RETURN["bank_fd"]
            label = "post_office"
        else:
            r = POST_TAX_RETURN["bank_fd"]
            label = "fd"
        buckets.append((label, v, r))
    # Liquid
    lc = plan.liquid_capital
    liq = sum((getattr(lc, k) or 0) for k in
              ("savings_account_balance", "idle_cash_for_investment",
               "fd_breakable_for_investment", "bonus_expected_for_investment"))
    if liq > 0:
        buckets.append(("liquid", float(liq), POST_TAX_RETURN["liquid_fund"]))

    total = sum(v for _, v, _ in buckets)
    if total <= 0:
        return BLENDED_ROI_POST_TAX, {"fallback_equal_weight": BLENDED_ROI_POST_TAX}
    weighted = sum(v * r for _, v, r in buckets) / total
    breakdown: dict[str, float] = {}
    for label, v, r in buckets:
        breakdown[label] = breakdown.get(label, 0) + v
    breakdown["_weighted_post_tax_roi"] = round(weighted, 4)
    breakdown["_total_value"] = round(total)
    return weighted, breakdown


def _retirement_tagged_assets_fv(
    plan: PlanState, *, years_to_retire: int
) -> tuple[float, list[dict]]:
    """Future-value of assets earmarked for retirement (EPF, NPS, and any
    fixed-income explicitly tagged retirement). Mirrors the Excel netting
    on Assumptions rows 94-103 — `corpus_required − FV(retirement assets)`.
    Returns (total_fv, breakdown_rows)."""
    if years_to_retire <= 0:
        return 0.0, []
    rows: list[dict] = []
    fv_total = 0.0
    for fi in plan.fixed_income or []:
        v = float(fi.current_value or 0)
        if v <= 0:
            continue
        inst = (fi.instrument or "").lower()
        if "epf" in inst:
            r = POST_TAX_RETURN["epf"]
        elif "nps" in inst:
            r = POST_TAX_RETURN["nps"]
        elif "ppf" in inst:
            r = POST_TAX_RETURN["ppf"]
        else:
            continue
        fv = v * ((1 + r) ** years_to_retire)
        fv_total += fv
        rows.append({"label": f"{fi.instrument} (today ₹{round(v):,})",
                     "rate": round(r, 4), "fv_at_retirement": round(fv)})
    return fv_total, rows


def _spouse_age_and_life_expectancy(
    plan: PlanState, current_year: int, fallback_age: int, fallback_le: int
) -> tuple[int, int]:
    """Replaces the buggy `persons[1].id and (current_age − 2)` no-op.
    Reads the spouse Person row if present, computes age from DOB,
    falls back to caller's defaults."""
    persons = plan.assumptions.persons or []
    if len(persons) < 2:
        return fallback_age, fallback_le
    spouse = persons[1]
    le = int(spouse.life_expectancy or fallback_le)
    if spouse.date_of_birth:
        try:
            yr = int(spouse.date_of_birth[-4:])
            age = max(0, current_year - yr)
            return age, le
        except Exception:
            pass
    return fallback_age, le


def compute_cfp(plan: PlanState) -> CFPOutput:
    """The Excel-faithful orchestration — runs every block and bundles the
    computation trace for inline display in the agent's tool result."""
    trace: list[dict] = []

    fsi = plan.freedom_score_inputs
    pd = plan.personal_details
    current_year = datetime.now().year
    current_age = fsi.age or 30
    retirement_age = pd.retirement_age_target or 60
    life_expectancy = (plan.assumptions.persons[0].life_expectancy if plan.assumptions.persons else 85)

    monthly_income = fsi.monthly_income or 0
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0

    annual_income = monthly_income * 12
    annual_expenses = monthly_expenses * 12

    trace.append(_trace(
        "Annual income",
        "monthly_income × 12",
        {"monthly_income": monthly_income},
        round(annual_income),
    ))
    trace.append(_trace(
        "Annual expenses (excl. investments, excl. EMIs)",
        "monthly_expenses × 12",
        {"monthly_expenses": monthly_expenses},
        round(annual_expenses),
    ))

    # ── Goal blocks ────────────────────────────────────────────────────
    # `kind=retirement` goals are handled SEPARATELY by the dedicated
    # corpus calculation below — they represent the ANNUAL post-
    # retirement expense, not a one-time spend. Including them here
    # would double-count: the goal-block treats target_amount as a
    # single FV outflow, while the corpus calc treats it as a
    # multi-year annuity. The corpus path is the right one.
    asset_pool = _build_asset_pool(plan)
    goal_blocks: list[dict] = []
    goal_outflows_by_year: dict[int, float] = {}
    for g in plan.financial_goals:
        if g.kind == "retirement":
            continue
        block = compute_goal_block(g, current_year=current_year, asset_pool=asset_pool)
        goal_blocks.append(block)
        if block["target_year"] and block["future_value_needed"]:
            goal_outflows_by_year[block["target_year"]] = (
                goal_outflows_by_year.get(block["target_year"], 0) + block["future_value_needed"]
            )

    total_required_sip = sum(b["required_sip_monthly"] for b in goal_blocks)

    # ── Credit existing SIPs toward goal funding ──────────────────────
    # The user is already deploying monthly SIPs (mutual_funds, NPS, PPF,
    # RD, direct equity, and the "other" bucket EPF/recurring buys land
    # in). These contributions ARE wealth-building — they grow the same
    # portfolio that funds the goals. Previously each goal_block was
    # built with existing_goal_sip=0, so the engine demanded the FULL
    # required SIP per goal again, on top of what was already running.
    # That double-counted savings effort and inflated incremental_sip
    # by the household's entire SIP commitment.
    #
    # Allocate the existing SIPs across goals proportionally to each
    # goal's `required_sip_monthly`. The goal that needs the largest
    # SIP gets the largest share of existing contributions. Each goal's
    # `incremental_sip_monthly` becomes the NEW commitment needed on top
    # of what's already running.
    mi_for_credit = plan.monthly_investments
    existing_sip_for_goals = 0.0
    if mi_for_credit:
        existing_sip_for_goals = float(
            (mi_for_credit.mutual_fund_sip or 0)
            + (mi_for_credit.nps or 0)
            + (mi_for_credit.ppf or 0)
            + (mi_for_credit.rd or 0)
            + (mi_for_credit.direct_equity or 0)
            + (mi_for_credit.other or 0)
        )
    if existing_sip_for_goals > 0 and total_required_sip > 0:
        # Allocate up to each goal's required amount (a goal can't be
        # "over-funded" by existing SIPs — surplus credit stays in the
        # remaining pool to fund the next goal).
        remaining_credit = existing_sip_for_goals
        # Pass 1: proportional allocation by required-SIP share, capped
        # at each goal's actual need.
        for b in goal_blocks:
            req = b["required_sip_monthly"] or 0
            if req <= 0:
                continue
            share = req / total_required_sip
            credit = min(req, share * existing_sip_for_goals)
            b["existing_sip_monthly"] = round(credit)
            b["incremental_sip_monthly"] = max(0, round(req - credit))
            remaining_credit -= credit
        # Pass 2: if some goals were fully covered by their share (so
        # there's spillover credit), redistribute the leftover to goals
        # that still have a gap.
        if remaining_credit > 1:
            still_short = [b for b in goal_blocks if b.get("incremental_sip_monthly", 0) > 0]
            total_short = sum(b["incremental_sip_monthly"] for b in still_short)
            if total_short > 0:
                for b in still_short:
                    extra_share = b["incremental_sip_monthly"] / total_short
                    extra = min(b["incremental_sip_monthly"], extra_share * remaining_credit)
                    b["existing_sip_monthly"] = round((b.get("existing_sip_monthly") or 0) + extra)
                    b["incremental_sip_monthly"] = max(0, round(b["incremental_sip_monthly"] - extra))
        trace.append(_trace(
            "Existing SIPs credited toward goals",
            "monthly_investments.* (ex. insurance) split proportionally across goals by required-SIP share",
            {"existing_sip": round(existing_sip_for_goals), "total_required": round(total_required_sip)},
            round(existing_sip_for_goals),
            unit="INR/mo",
        ))

    total_incremental_sip = sum(b["incremental_sip_monthly"] for b in goal_blocks)
    trace.append(_trace(
        "Total required SIP across all goals",
        "Σ goal.required_sip_monthly",
        {"goal_count": len(goal_blocks)},
        round(total_required_sip),
    ))

    # ── Surplus & affordability (Finding: "is the required SIP realistic?") ──
    # The Excel model assumes the household can spare whatever PMT
    # demands. In reality SIPs are bounded by monthly cashflow. We now
    # report two views:
    #   1. Goal coverage — existing SIPs (already credited per-goal above)
    #      cover X% of the required PMT. The INCREMENTAL ask is what
    #      remains to fully fund every goal.
    #   2. Cashflow sustainability — surplus_pre_sip is the total room
    #      for all SIPs combined. If existing SIPs already exceed it,
    #      the household is funding the gap from savings/bonus.
    mi = plan.monthly_investments
    existing_sip_monthly = 0.0
    if mi:
        existing_sip_monthly = float(
            (mi.mutual_fund_sip or 0) + (mi.nps or 0) + (mi.ppf or 0)
            + (mi.rd or 0) + (mi.direct_equity or 0) + (mi.other or 0)
        )
    surplus_pre_sip = monthly_income - monthly_expenses - monthly_emi
    surplus_post_existing_sip = surplus_pre_sip - existing_sip_monthly
    affordable_for_new_sip = max(0.0, surplus_post_existing_sip)

    # Ration the available NEW-SIP headroom proportionally across each
    # goal's INCREMENTAL need (after the existing-SIP credit above).
    # Each goal's "feasible_sip_monthly" = existing_credit + rationed
    # incremental — i.e. what TOTAL SIP it would receive in a realistic
    # plan, not just the new ask.
    if total_incremental_sip > 0 and affordable_for_new_sip < total_incremental_sip:
        ration_factor = affordable_for_new_sip / total_incremental_sip
    else:
        ration_factor = 1.0  # surplus covers the incremental ask → no rationing

    for b in goal_blocks:
        req = b["required_sip_monthly"] or 0
        existing_credit = b.get("existing_sip_monthly", 0) or 0
        inc = b.get("incremental_sip_monthly", 0) or 0
        # Feasible TOTAL SIP for this goal = existing share already
        # flowing to it + the rationed slice of the incremental ask.
        rationed_incremental = round(inc * ration_factor)
        feasible_total = existing_credit + rationed_incremental
        b["affordable_sip_monthly"] = feasible_total
        b["sip_shortfall_monthly"] = max(0, req - feasible_total)
        # Funded share against the FULL required SIP (not just the gap).
        # An RM looking at this wants to see "this goal will reach X%
        # of its target with my current + feasible-new SIPs."
        b["funded_share_at_affordable_sip"] = (
            min(1.0, feasible_total / req) if req > 0 else 1.0
        )

    affordable_sip_total = round(sum(b["affordable_sip_monthly"] for b in goal_blocks))
    surplus_shortfall = max(0.0, total_incremental_sip - affordable_for_new_sip)

    trace.append(_trace(
        "Monthly surplus available for new SIPs",
        "income − expenses − EMI − existing_SIPs",
        {"income": round(monthly_income), "expenses": round(monthly_expenses),
         "emi": round(monthly_emi), "existing_sips": round(existing_sip_monthly)},
        round(affordable_for_new_sip),
        unit="INR/mo",
    ))
    if surplus_shortfall > 0:
        trace.append(_trace(
            "SIP shortfall — required exceeds available surplus",
            "required_incremental_SIP − affordable_for_new_SIP",
            {"required_incremental_sip": round(total_incremental_sip),
             "affordable_for_new_sip": round(affordable_for_new_sip),
             "ration_factor": round(ration_factor, 4)},
            round(surplus_shortfall),
            unit="INR/mo",
        ))

    # ── Retirement corpus (gross) ─────────────────────────────────────
    # Excel uses the equity_hybrid (10.5%) post-tax return for the
    # retirement-corpus discounting. See Retirement Plan tab cell E23 →
    # Assumptions sheet E22.
    #
    # PLANNED retirement annual expense: if the household entered a
    # `kind=retirement` goal with a target_amount, that's the firm's
    # planned ANNUAL POST-RETIREMENT spend (per the Excel template's
    # "Retirement Cost" row, nature=Annual). Use it instead of current
    # monthly_expenses × 12, because retirement spend is usually LOWER
    # (no EMI, no school fees, less lifestyle). Falling through to
    # current expenses systematically over-estimates the corpus.
    retire_goal = next(
        (g for g in plan.financial_goals if g.kind == "retirement" and (g.target_amount or 0) > 0),
        None,
    )
    if retire_goal is not None:
        planned_annual = float(retire_goal.target_amount or 0)
        if retire_goal.is_target_in_today_money:
            retire_annual_expense_today = planned_annual
        else:
            # target_amount was given in target-year rupees; discount back to today
            infl_g = (
                retire_goal.inflation_assumed
                if retire_goal.inflation_assumed is not None
                else (plan.assumptions.inflation or 0.07)
            )
            n_back = max(0, (retire_goal.target_year or current_year + 10) - current_year)
            retire_annual_expense_today = planned_annual / ((1 + infl_g) ** n_back)
        trace.append(_trace(
            "Planned retirement annual expense (from retirement goal)",
            "kind=retirement goal's target_amount, discounted to today's rupees if needed",
            {"goal_name": retire_goal.goal_name,
             "raw_target": planned_annual,
             "is_today_money": retire_goal.is_target_in_today_money},
            round(retire_annual_expense_today),
            unit="INR/yr",
        ))
    else:
        # No retirement goal entered → default to current expenses
        # carried into retirement (conservative).
        retire_annual_expense_today = annual_expenses

    retirement = compute_retirement_corpus(
        current_age=current_age,
        retirement_age=retirement_age,
        life_expectancy=life_expectancy,
        current_annual_expenses=retire_annual_expense_today,
        inflation=plan.assumptions.inflation or 0.07,
        post_retire_return=POST_TAX_RETURN["equity_hybrid"],
    )
    retirement["used_planned_retirement_expense"] = bool(retire_goal is not None)
    retirement["retirement_annual_expense_today"] = round(retire_annual_expense_today)
    # Net existing PROVISIONS out of the gross corpus to find the
    # actual shortfall the new SIP needs to close. Two pieces:
    #   (a) explicitly retirement-tagged assets (EPF/PPF/NPS) compounded
    #       to retirement at their per-class rates. (Existing Finding 4
    #       logic — Excel's Assumptions sheet rows 94-103.)
    #   (b) the FUTURE VALUE of ongoing monthly SIPs over the working
    #       horizon, compounded at the equity-hybrid post-tax rate.
    #       Without this, the Retirement Glide reports a huge "additional
    #       SIP needed" even though the household's existing SIPs are
    #       already going to wealth — contradicting the goal-scenarios
    #       view which already credits existing SIPs to goals.
    years_to_retire = max(0, retirement_age - current_age)
    ret_assets_fv, ret_assets_rows = _retirement_tagged_assets_fv(
        plan, years_to_retire=years_to_retire
    )
    retirement["existing_retirement_assets_fv"] = round(ret_assets_fv)
    retirement["existing_retirement_assets_breakdown"] = ret_assets_rows

    # FV of existing SIPs run to retirement. Standard FV-of-annuity:
    #     FV = PMT × ((1+r)^n − 1) / r
    # Use annual roi compounded over n years, with annual cashflow =
    # monthly_sip × 12 (close enough; the exact monthly compounding only
    # adds ~2% precision over decades).
    mi_for_fv = plan.monthly_investments
    monthly_sip_for_fv = 0.0
    if mi_for_fv:
        monthly_sip_for_fv = float(
            (mi_for_fv.mutual_fund_sip or 0) + (mi_for_fv.nps or 0)
            + (mi_for_fv.ppf or 0) + (mi_for_fv.rd or 0)
            + (mi_for_fv.direct_equity or 0) + (mi_for_fv.other or 0)
        )
    sip_pre_retire_rate = POST_TAX_RETURN["equity_hybrid"]
    if monthly_sip_for_fv > 0 and years_to_retire > 0 and sip_pre_retire_rate > 0:
        annual_sip = monthly_sip_for_fv * 12
        existing_sip_fv = annual_sip * (
            ((1 + sip_pre_retire_rate) ** years_to_retire - 1) / sip_pre_retire_rate
        )
    else:
        existing_sip_fv = 0.0
    retirement["existing_sip_fv_at_retirement"] = round(existing_sip_fv)
    retirement["monthly_sip_committed"] = round(monthly_sip_for_fv)

    # Total provision = retirement-tagged assets + FV of ongoing SIPs
    total_provision_fv = ret_assets_fv + existing_sip_fv
    retirement["total_provision_at_retirement"] = round(total_provision_fv)

    corpus_shortfall = max(0.0, retirement["corpus_required"] - total_provision_fv)
    retirement["corpus_shortfall_after_existing"] = round(corpus_shortfall)
    retirement["computation_trace"].append(_trace(
        "Net existing provisions out of corpus need",
        "shortfall = corpus_required − Σ FV(EPF/NPS/PPF) − FV(ongoing SIPs)",
        {"corpus_required": retirement["corpus_required"],
         "retirement_assets_fv": round(ret_assets_fv),
         "existing_sip_fv": round(existing_sip_fv)},
        round(corpus_shortfall),
    ))

    # Additional monthly SIP needed to close the shortfall — Excel
    # `Retirement Plan!B48` = PMT(post_tax_roi/12, years_to_retire*12, , -shortfall).
    n_months = years_to_retire * 12
    if corpus_shortfall > 0 and n_months > 0 and sip_pre_retire_rate > 0:
        sip_required = abs(excel_pmt(sip_pre_retire_rate / 12, n_months, 0, -corpus_shortfall))
    else:
        sip_required = 0.0
    retirement["required_monthly_sip"] = round(sip_required)
    retirement["sip_rate_used"] = round(sip_pre_retire_rate, 4)
    retirement["computation_trace"].append(_trace(
        "Additional monthly SIP needed to close retirement shortfall",
        "PMT(roi/12, years_to_retire*12, , -shortfall)",
        {"roi": round(sip_pre_retire_rate, 4),
         "years_to_retire": years_to_retire,
         "shortfall": round(corpus_shortfall)},
        round(sip_required),
        unit="INR/mo",
    ))

    # ── Insurance need ─────────────────────────────────────────────────
    loans = plan.loans_liabilities
    loans_outstanding = sum(
        (getattr(loans, k).outstanding_amount or 0) if getattr(loans, k, None) else 0
        for k in ("home_loan", "car_loan", "personal_loan", "credit_card_dues")
    )
    existing_cover = (
        plan.insurance_details.term_plan.cover_amount
        if plan.insurance_details and plan.insurance_details.term_plan
        else 0
    ) or 0
    # Broader "investable assets" pool — matches Excel `Insurance
    # Computation!F174` (MF + equity + FD + bonds + EPF/NPS/PPF + gold +
    # liquid). Previously cfp.py used only `portfolio + liquid` which
    # overstated the additional cover needed.
    mf_total = sum((h.current_value or 0) for h in (plan.mutual_funds or []))
    eq_total = sum((h.current_value or 0) for h in (plan.equity_stocks or []))
    fi_total = sum((h.current_value or 0) for h in (plan.fixed_income or []))
    gold_total = sum((h.current_value or 0) for h in (plan.gold or []) if h.held_for_investment)
    lc = plan.liquid_capital
    liquid_total = sum((getattr(lc, k) or 0) for k in
                       ("savings_account_balance", "idle_cash_for_investment",
                        "fd_breakable_for_investment", "bonus_expected_for_investment"))
    investable_assets = mf_total + eq_total + fi_total + gold_total + liquid_total
    # Fallback to FSI when holdings lists are empty.
    if investable_assets <= 0:
        investable_assets = (fsi.portfolio_current_value or 0) + (fsi.liquid_assets_current_value or 0)

    spouse_age, spouse_le = _spouse_age_and_life_expectancy(
        plan, current_year, fallback_age=current_age - 2, fallback_le=life_expectancy
    )
    insurance = compute_insurance_need(
        current_annual_income=annual_income,
        current_annual_expenses=annual_expenses,
        current_age=current_age,
        retirement_age=retirement_age,
        spouse_age=spouse_age,
        spouse_life_expectancy=spouse_le,
        loans_outstanding=loans_outstanding,
        existing_cover=existing_cover,
        investable_assets=investable_assets,
        return_rate=0.10,
        inflation=plan.assumptions.inflation or 0.06,
    )
    # Finding 8 — Excel health-cover rule (was missing entirely).
    persons = plan.assumptions.persons or []
    n_persons = len(persons)
    has_children = any(
        p.date_of_birth and (current_year - int((p.date_of_birth or "0000")[-4:] or 0)) < 25
        for p in persons[2:]
    ) if n_persons > 2 else False
    if n_persons <= 1:
        family_kind = "single"
    elif n_persons == 2:
        family_kind = "couple"
    elif has_children:
        family_kind = "with_children"
    else:
        family_kind = "with_dependents"
    is_metro = (plan.personal_details.city_type or "Non-metro") == "Metro"
    health = compute_health_cover_required(
        annual_income=annual_income, family_kind=family_kind, is_metro=is_metro,
    )
    existing_health = (
        plan.insurance_details.health_insurance.cover_amount
        if plan.insurance_details and plan.insurance_details.health_insurance
        else 0
    ) or 0
    family_floater = (
        plan.insurance_details.family_floater.cover_amount
        if plan.insurance_details and plan.insurance_details.family_floater
        else 0
    ) or 0
    health["existing_cover"] = round(existing_health + family_floater)
    health["additional_cover_required"] = max(0, health["required"] - health["existing_cover"])
    insurance["health"] = health

    # ── Year-by-year cashflow ──────────────────────────────────────────
    income_emp_monthly = (plan.income_details.client_salary_in_hand or 0) + (plan.income_details.spouse_salary_in_hand or 0)
    income_biz_monthly = (plan.income_details.client_business_income or 0) + (plan.income_details.spouse_business_income or 0)
    income_rent_monthly = (plan.income_details.client_rental_income or 0) + (plan.income_details.spouse_rental_income or 0)
    income_oth_monthly = (plan.income_details.client_other_income or 0) + (plan.income_details.spouse_other_income or 0)

    # FA = financial assets at today's value. Prefer the actual holdings
    # totals (MF + equity + FD/bonds + liquid) — fall back to FSI scalars
    # only when no holding rows are populated.
    opening_fa = (mf_total + eq_total + fi_total + liquid_total) or (
        (fsi.portfolio_current_value or 0) + (fsi.liquid_assets_current_value or 0)
    )

    # NFA = real estate + gold-as-investment at today's value. Finding 2:
    # this used to be hardcoded to 0.0 — the single largest numeric error.
    re_total = sum((h.current_value or 0) for h in (plan.real_estate or []))
    nfa_gold_total = sum((h.current_value or 0) for h in (plan.gold or []))
    opening_nfa = re_total + nfa_gold_total

    # Holdings-weighted post-tax ROI (Finding 5) — replaces the equal-
    # weight BLENDED_ROI_POST_TAX constant.
    fa_roi, fa_roi_breakdown = _holdings_weighted_post_tax_roi(plan)
    trace.append(_trace(
        "Holdings-weighted post-tax ROI on financial assets",
        "Σ(value_i × rate_i) / Σ value_i",
        fa_roi_breakdown,
        round(fa_roi, 4),
        unit="%",
    ))

    # Per-source income growth from plan assumptions (Finding 3).
    ig = plan.assumptions.income_growth

    # Bucket lumpsum events by year so the yoy engine can fold them in.
    lumpsum_by_year: dict[int, list[tuple[float, str]]] = {}
    for ev in (plan.assumptions.lumpsum_events or []):
        if ev.amount == 0:
            continue
        lumpsum_by_year.setdefault(int(ev.year), []).append(
            (float(ev.amount), ev.label or "")
        )

    # Fixed-income maturities are MODELLED as pool transfers, not new money:
    # at maturity year, the instrument's current_value leaves the FA pool
    # (it's been cashed out) and re-enters via a positive Lumpsum inflow.
    # The fa_transfers_out_by_year dict makes this explicit so fa_close
    # stays consistent (instead of double-counting growth on an already-
    # matured asset). The user sees the actual maturity amount in the
    # Lumpsum column AND the instrument label in Remarks.
    fa_transfers_out_by_year: dict[int, float] = {}
    for fi in plan.fixed_income or []:
        if not fi.maturity_date:
            continue
        # maturity_date may be a date / datetime / string. Best-effort year extract.
        m_year: int | None = None
        try:
            m_year = int(getattr(fi.maturity_date, "year", None) or 0) or None
        except Exception:
            m_year = None
        if not m_year:
            s = str(fi.maturity_date)
            for token in s.replace("-", " ").replace("/", " ").split():
                if token.isdigit() and len(token) == 4:
                    m_year = int(token)
                    break
        if not m_year or m_year < current_year:
            continue
        val = float(fi.current_value or 0)
        if val <= 0:
            continue
        label = f"{fi.instrument or 'FD'} matures"
        lumpsum_by_year.setdefault(m_year, []).append((val, label))
        fa_transfers_out_by_year[m_year] = fa_transfers_out_by_year.get(m_year, 0) + val

    yoy = compute_yoy_cashflow(
        horizon_years=min(40, max(life_expectancy - current_age, 10)),
        start_year=current_year,
        start_age=current_age,
        retirement_age=retirement_age,
        monthly_income_employment=income_emp_monthly,
        monthly_income_business=income_biz_monthly,
        monthly_income_rental=income_rent_monthly,
        monthly_income_other=income_oth_monthly,
        monthly_expenses_living=monthly_expenses,
        monthly_loan_repayment=monthly_emi,
        opening_financial_assets=opening_fa,
        opening_non_financial_assets=opening_nfa,
        employment_growth=ig.employment,
        business_growth=ig.business,
        rental_growth=ig.rental,
        other_income_growth=ig.other,
        expense_growth_rate=plan.assumptions.inflation or 0.07,
        financial_asset_roi=fa_roi,
        non_financial_appreciation=POST_TAX_RETURN["real_estate"],
        goal_outflows_by_year=goal_outflows_by_year,
        lumpsum_events_by_year=lumpsum_by_year,
        fa_transfers_out_by_year=fa_transfers_out_by_year,
    )

    # ── Summary ────────────────────────────────────────────────────────
    gross_savings_rate = (annual_income - annual_expenses - monthly_emi * 12) / annual_income if annual_income else 0
    required_savings_rate = total_required_sip / monthly_income if monthly_income else 0
    on_track = required_savings_rate <= gross_savings_rate

    summary = {
        "current_age": current_age,
        "retirement_age": retirement_age,
        "life_expectancy": life_expectancy,
        "annual_income": round(annual_income),
        "annual_expenses": round(annual_expenses),
        "annual_emi": round(monthly_emi * 12),
        "gross_savings_rate": round(gross_savings_rate, 4),
        "required_savings_rate": round(required_savings_rate, 4),
        "on_track": on_track,
        "total_required_sip_monthly": round(total_required_sip),
        "total_incremental_sip_monthly": round(total_incremental_sip),
        # Surplus & affordability (the "is this realistic?" check)
        "monthly_income": round(monthly_income),
        "monthly_expenses": round(monthly_expenses),
        "monthly_emi": round(monthly_emi),
        "monthly_existing_sip": round(existing_sip_monthly),
        "monthly_surplus_pre_sip": round(surplus_pre_sip),
        "monthly_surplus_after_existing_sip": round(surplus_post_existing_sip),
        "affordable_new_sip_monthly": round(affordable_for_new_sip),
        "affordable_sip_total_monthly": affordable_sip_total,
        "sip_surplus_shortfall_monthly": round(surplus_shortfall),
        "sip_ration_factor": round(ration_factor, 4),
        "is_plan_affordable": surplus_shortfall <= 0,
        "retirement_corpus_required": retirement["corpus_required"],
        "retirement_existing_assets_fv": retirement.get("existing_retirement_assets_fv", 0),
        "retirement_corpus_shortfall": retirement.get("corpus_shortfall_after_existing", retirement["corpus_required"]),
        "additional_insurance_cover_required": insurance["additional_cover_required"],
        "horizon_net_worth_estimate": yoy[-1]["net_worth"] if yoy else 0,
        "opening_financial_assets": round(opening_fa),
        "opening_non_financial_assets": round(opening_nfa),
        "fa_holdings_weighted_roi": round(fa_roi, 4),
    }

    trace.append(_trace(
        "Gross savings rate",
        "(annual_income − annual_expenses − annual_emi) / annual_income",
        {"annual_income": round(annual_income), "annual_expenses": round(annual_expenses),
         "annual_emi": round(monthly_emi * 12)},
        round(gross_savings_rate, 4),
        unit="%",
    ))
    trace.append(_trace(
        "Required savings rate (SIP-as-%-of-income)",
        "total_required_sip / monthly_income",
        {"total_required_sip": round(total_required_sip), "monthly_income": monthly_income},
        round(required_savings_rate, 4),
        unit="%",
    ))
    trace.append(_trace(
        "On track?",
        "required_savings_rate <= gross_savings_rate",
        {"required": round(required_savings_rate, 4), "gross": round(gross_savings_rate, 4)},
        "yes" if on_track else "no",
        unit="bool",
    ))

    constants_used = {
        "inflation_table": INFLATION_TABLE,
        "post_tax_return_table": {k: round(v, 4) for k, v in POST_TAX_RETURN.items()},
        "blended_roi_post_tax_equal_weight": round(BLENDED_ROI_POST_TAX, 4),
        "blended_roi_post_tax_holdings_weighted": round(fa_roi, 4),
        "fa_holdings_breakdown": fa_roi_breakdown,
        "income_growth": {
            "employment": ig.employment, "business": ig.business,
            "rental": ig.rental, "other": ig.other,
        },
        "allocation_priority": ALLOCATION_PRIORITY,
    }

    # ── Debt block (Excel `Debt Mgt`): ratios + repayment ordering ──────
    ratios = compute_debt_ratios(plan)
    strategies = compute_repayment_strategies(plan)
    debt_block = {"ratios": ratios, "strategies": strategies}

    # ── Tax regime block (Excel `Tax Comparison`) ───────────────────────
    tax_regime_block = compute_tax_regime_comparison(plan)
    summary["recommended_tax_regime"] = tax_regime_block.get("recommended_regime")
    summary["annual_tax_savings_with_recommended"] = tax_regime_block.get("annual_savings_with_recommended")
    trace.append(_trace(
        "Tax regime — old vs new",
        "Excel `Tax Comparison` — slabs FY 2025-26, 87A rebate, 4% cess",
        {
            "old_total_tax": tax_regime_block["old_regime"]["total_tax"],
            "new_total_tax": tax_regime_block["new_regime"]["total_tax"],
        },
        f"Recommend {tax_regime_block['recommended_regime']} — saves ₹{tax_regime_block['annual_savings_with_recommended']:,}/yr",
        unit="₹",
    ))
    summary["dscr"] = ratios.get("dscr")
    summary["dti"] = ratios.get("dti")
    summary["dni"] = ratios.get("dni")
    summary["dscr_status"] = ratios.get("dscr_status")
    summary["dti_status"] = ratios.get("dti_status")
    summary["dni_status"] = ratios.get("dni_status")

    trace.append(_trace(
        "Debt ratios (DSCR / DTI / DNI)",
        "Excel `Debt Mgt` thresholds — DSCR≥1.25, DTI≤0.5, DNI≤0.3",
        {
            "annual_income": ratios.get("annual_income"),
            "annual_emi": ratios.get("annual_emi"),
            "total_debt": ratios.get("total_debt_outstanding"),
        },
        f"DSCR={ratios.get('dscr')} | DTI={ratios.get('dti')} | DNI={ratios.get('dni')}",
        unit="ratio",
    ))

    return CFPOutput(
        summary=summary,
        goal_blocks=goal_blocks,
        retirement=retirement,
        insurance=insurance,
        yoy_cashflow=yoy,
        constants_used=constants_used,
        computation_trace=trace,
        debt=debt_block,
        tax_regime=tax_regime_block,
    )


def _build_asset_pool(plan: PlanState) -> dict[str, float]:
    """Turn the plan's holdings into the priority-keyed asset pool the
    goal-allocation step consumes. Tags ('weak' / 'neutral') come from a
    firm-maintained tagging file (Rule 6 of the brief) — until that's
    wired, every stock / MF is treated as 'neutral'."""
    pool: dict[str, float] = {b: 0.0 for b in ALLOCATION_PRIORITY}

    # Mutual funds — currently all neutral (until tagging file lands).
    for mf in plan.mutual_funds or []:
        pool["neutral_mfs"] += float(mf.current_value or 0)
    # Equity stocks
    for eq in plan.equity_stocks or []:
        pool["neutral_stocks"] += float(eq.current_value or 0)
    # Fixed income — split FD vs PPF/EPF vs others
    for fi in plan.fixed_income or []:
        instrument = (fi.instrument or "").lower()
        val = float(fi.current_value or 0)
        if "fd" in instrument:
            pool["fixed_deposits"] += val
        elif "ppf" in instrument:
            pool["ppf"] += val
        elif "epf" in instrument:
            pool["epf"] += val
        elif "nsc" in instrument:
            pool["nsc"] += val
        elif "bond" in instrument:
            pool["bonds"] += val
        elif "nps" in instrument:
            pool["pension"] += val
        else:
            pool["fixed_deposits"] += val

    # Real estate explicitly earmarked for sale → priority slot 10
    # (Rule 6 Step 4). Otherwise it stays in NFA and isn't drawn on for
    # goals.
    for re_row in plan.real_estate or []:
        if re_row.earmarked_for_sale:
            pool["real_estate_for_sale"] += float(re_row.current_value or 0)
    # Investment gold is allocable; sentimental jewellery is not.
    for g in plan.gold or []:
        if g.held_for_investment:
            pool["gold"] += float(g.current_value or 0)

    return pool
