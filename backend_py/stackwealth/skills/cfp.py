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
    "wedding": 0.08,                # firm: Wedding Inflation (literal weddings)
    # Empirical from firm's reference workbook: child_marriage goals are
    # priced at general inflation (7%), not wedding inflation. The 8%
    # "Wedding Inflation" row in the firm's Assumptions sheet is reserved
    # for explicit wedding-ceremony goals; downstream child-marriage
    # withdrawals on the YoY tab are computed at 7%.
    "child_marriage": 0.07,
    "medical": 0.09,                # firm: Medical Inflation
    "lifestyle": 0.20,              # firm: Personalised (Lifestyle) inflation
    "real_estate": 0.08,            # firm: Real Estate Inflation
    "house_purchase": 0.08,
    "vacation": 0.07,               # firm YoY uses general inflation here
    "foreign_travel": 0.07,         # same — empirically 7% in firm Excel
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
    current_age: float,
    retirement_age: float,
    life_expectancy: float,
    retirement_annual_expenses_today: float,
    inflation: float = 0.07,
    # Excel `Retirement Plan!E22` → `Assumptions!E23` = equity-CONSERVATIVE
    # (large-cap) post-tax = 8.75%. This is the rate the corpus annuity is
    # discounted at — NOT the 10.5% hybrid rate (that one funds the SIP, see
    # `sip_funding_return`). The earlier code conflated the two and used
    # 10.5% for the discount, which understated the required corpus.
    corpus_discount_return: float = 0.0875,
    # Spouse inputs — when both are present the corpus is sized to the
    # SPOUSE's lifetime (Excel E14/E15: "providing for his wife's lifetime
    # also"), which is the whole premise of the firm's Retirement Plan tab.
    spouse_current_age: Optional[float] = None,
    spouse_life_expectancy: Optional[float] = None,
    # One-time post-retirement spend (Excel E26-E29) — e.g. a legacy gift /
    # orphanage donation. Inflated to its target year and funded by a
    # separate SIP.
    one_time_spend_today: float = 0.0,
    one_time_spend_years: Optional[float] = None,
    one_time_spend_inflation: Optional[float] = None,
    # FV of assets already earmarked for retirement, compounded to the
    # retirement date (Excel C36 = `10_Financial_Goals!Y21`).
    projected_existing_corpus_fv: float = 0.0,
    # Excel `Retirement Plan!C40` → `Assumptions!E22` = equity-HYBRID post-tax
    # = 10.5%. The accumulation rate used to size the monthly SIP.
    sip_funding_return: float = 0.105,
    # SIPs already running toward retirement (Excel E43) — netted off the
    # gross SIP to give the *additional* monthly commitment needed.
    ongoing_retirement_sip_monthly: float = 0.0,
) -> dict:
    """Cell-for-cell port of the firm's `Retirement Plan` tab.

    Section 1 — corpus required (rows 7-30):
        E10  years_to_retire     = retirement_age − current_age
        E14  spouse_age_at_ret   = retirement_age − (current_age − spouse_age)
        E15  post_retire_years   = spouse_life_exp − spouse_age_at_ret   (wife's lifetime)
        E20  annual_at_retire    = FV(inflation, E10, , −retire_expense_today)
        E24  real_return         = ((1+corpus_discount_return)/(1+inflation)) − 1
        E25  corpus_recurring    = PV(E24, E15, −E20, 0, 1)              (annuity due)
        E29  one_time_fv         = FV(inflation, one_time_years, , −one_time_today)
        E30  corpus_required     = E25 + E29

    Section 2 — additional SIP (rows 35-44):
        C37  shortfall_recurring = E25 − projected_existing_corpus_fv
        D37  shortfall_one_time  = E29
        C41  sip_recurring       = PMT(sip_funding_return/12, E10*12, 0, −C37)
        D41  sip_one_time        = PMT(sip_funding_return/12, one_time_years*12, 0, −D37)
        E41  gross_monthly_sip   = C41 + D41
        E44  required_monthly_sip = E41 − ongoing_retirement_sip_monthly
    """
    trace: list[dict] = []
    years_to_retire = max(0.0, retirement_age - current_age)               # E10

    # ── Post-retirement horizon — spouse lifetime when a spouse exists ───
    if spouse_current_age is not None and spouse_life_expectancy is not None:
        spouse_age_at_retire = retirement_age - (current_age - spouse_current_age)  # E14
        post_retire_years = max(0.0, spouse_life_expectancy - spouse_age_at_retire) # E15
        horizon_basis = "spouse_lifetime"
        trace.append(_trace(
            "Spouse's age at the time of retirement",
            "retirement_age − (current_age − spouse_current_age)",
            {"retirement_age": round(retirement_age, 1), "current_age": round(current_age, 1),
             "spouse_current_age": round(spouse_current_age, 1)},
            round(spouse_age_at_retire, 1),
            unit="years",
        ))
        trace.append(_trace(
            "Years to be served post-retirement (spouse's lifetime)",
            "spouse_life_expectancy − spouse_age_at_retirement",
            {"spouse_life_expectancy": spouse_life_expectancy,
             "spouse_age_at_retirement": round(spouse_age_at_retire, 1)},
            round(post_retire_years, 1),
            unit="years",
        ))
    else:
        spouse_age_at_retire = None
        post_retire_years = max(0.0, life_expectancy - retirement_age)
        horizon_basis = "self_lifetime"
        trace.append(_trace(
            "Years to be served post-retirement (self lifetime)",
            "life_expectancy − retirement_age",
            {"life_expectancy": life_expectancy, "retirement_age": round(retirement_age, 1)},
            round(post_retire_years, 1),
            unit="years",
        ))

    # ── Section 1: corpus required ───────────────────────────────────────
    annual_at_retire = excel_fv(inflation, years_to_retire, 0, -retirement_annual_expenses_today)  # E20
    trace.append(_trace(
        "Living expense at retirement (inflation-grown)",
        "FV(inflation, years_to_retire, , −retirement_expense_today)",
        {"inflation": round(inflation, 4), "years_to_retire": round(years_to_retire, 1),
         "retirement_expense_today": round(retirement_annual_expenses_today)},
        round(annual_at_retire),
    ))

    real_return = ((1 + corpus_discount_return) / (1 + inflation)) - 1                   # E24
    trace.append(_trace(
        "Inflation-adjusted real return during retirement",
        "((1+corpus_discount_return)/(1+inflation)) − 1",
        {"corpus_discount_return": round(corpus_discount_return, 4), "inflation": round(inflation, 4)},
        round(real_return, 4),
        unit="%",
    ))

    corpus_recurring = abs(excel_pv(real_return, post_retire_years, -annual_at_retire, 0, when=1))  # E25
    trace.append(_trace(
        "Retirement corpus for recurring spend (annuity due)",
        "PV(real_return, post_retire_years, −annual_at_retire, 0, 1)",
        {"real_return": round(real_return, 4), "post_retire_years": round(post_retire_years, 1),
         "annual_at_retire": round(annual_at_retire)},
        round(corpus_recurring),
    ))

    # One-time post-retirement spend (E26-E29).
    ot_infl = one_time_spend_inflation if one_time_spend_inflation is not None else inflation
    ot_years = float(one_time_spend_years) if one_time_spend_years is not None else 0.0
    if one_time_spend_today > 0 and ot_years > 0:
        one_time_fv = excel_fv(ot_infl, ot_years, 0, -one_time_spend_today)                          # E29
        trace.append(_trace(
            "One-time post-retirement spend, grown to its target year",
            "FV(inflation, one_time_years, , −one_time_spend_today)",
            {"inflation": round(ot_infl, 4), "one_time_years": round(ot_years, 1),
             "one_time_spend_today": round(one_time_spend_today)},
            round(one_time_fv),
        ))
    else:
        one_time_fv = 0.0

    corpus_required = corpus_recurring + one_time_fv                                                  # E30
    trace.append(_trace(
        "Total retirement corpus needed (recurring + one-time)",
        "corpus_recurring + one_time_fv",
        {"corpus_recurring": round(corpus_recurring), "one_time_fv": round(one_time_fv)},
        round(corpus_required),
    ))

    # ── Section 2: additional SIP to close the gap ───────────────────────
    shortfall_recurring = max(0.0, corpus_recurring - projected_existing_corpus_fv)                   # C37
    shortfall_one_time = max(0.0, one_time_fv)                                                        # D37
    trace.append(_trace(
        "Shortfall in recurring corpus (net of earmarked assets' FV)",
        "corpus_recurring − projected_existing_corpus_fv",
        {"corpus_recurring": round(corpus_recurring),
         "projected_existing_corpus_fv": round(projected_existing_corpus_fv)},
        round(shortfall_recurring),
    ))

    n_rec = round(years_to_retire)                                                                    # C39
    n_ot = round(ot_years)                                                                            # D39
    if shortfall_recurring > 0 and n_rec > 0 and sip_funding_return > 0:
        sip_recurring = abs(excel_pmt(sip_funding_return / 12, n_rec * 12, 0, -shortfall_recurring))  # C41
    else:
        sip_recurring = 0.0
    if shortfall_one_time > 0 and n_ot > 0 and sip_funding_return > 0:
        sip_one_time = abs(excel_pmt(sip_funding_return / 12, n_ot * 12, 0, -shortfall_one_time))     # D41
    else:
        sip_one_time = 0.0

    gross_monthly_sip = sip_recurring + sip_one_time                                                  # E41
    trace.append(_trace(
        "Gross additional monthly SIP (recurring + one-time)",
        "PMT(sip_funding_return/12, years*12, 0, −shortfall)  summed over both plans",
        {"sip_funding_return": round(sip_funding_return, 4),
         "sip_recurring": round(sip_recurring), "sip_one_time": round(sip_one_time)},
        round(gross_monthly_sip),
        unit="INR/mo",
    ))

    required_monthly_sip = max(0.0, gross_monthly_sip - ongoing_retirement_sip_monthly)               # E44
    if ongoing_retirement_sip_monthly > 0:
        trace.append(_trace(
            "Additional SIP needed after netting ongoing SIPs",
            "gross_monthly_sip − ongoing_retirement_sip",
            {"gross_monthly_sip": round(gross_monthly_sip),
             "ongoing_retirement_sip": round(ongoing_retirement_sip_monthly)},
            round(required_monthly_sip),
            unit="INR/mo",
        ))

    total_shortfall = shortfall_recurring + shortfall_one_time

    return {
        "current_age": round(current_age, 1),
        "retirement_age": round(retirement_age, 1),
        "life_expectancy": life_expectancy,
        "spouse_current_age": round(spouse_current_age, 1) if spouse_current_age is not None else None,
        "spouse_life_expectancy": spouse_life_expectancy,
        "spouse_age_at_retirement": round(spouse_age_at_retire, 1) if spouse_age_at_retire is not None else None,
        "horizon_basis": horizon_basis,
        "years_to_retire": round(years_to_retire, 1),
        "post_retire_years": round(post_retire_years, 1),
        "years_post_retirement": round(post_retire_years, 1),  # alias for canvas
        # Expenses
        "annual_expense_today": round(retirement_annual_expenses_today),
        "retirement_annual_expense_today": round(retirement_annual_expenses_today),
        "annual_expenses_at_retirement": round(annual_at_retire),
        "annual_expense_at_retirement": round(annual_at_retire),
        # Rates
        "inflation_during_retirement": round(inflation, 4),
        "corpus_discount_return": round(corpus_discount_return, 4),
        "pre_retire_return": round(corpus_discount_return, 4),   # alias
        "post_retire_return": round(corpus_discount_return, 4),  # alias
        "real_return_used": round(real_return, 4),
        "real_return_during_retirement": round(real_return, 4),
        "sip_funding_return": round(sip_funding_return, 4),
        "sip_rate_used": round(sip_funding_return, 4),
        # Corpus
        "corpus_recurring": round(corpus_recurring),
        "one_time_spend_today": round(one_time_spend_today),
        "one_time_spend_years": round(ot_years, 1),
        "one_time_spend_fv": round(one_time_fv),
        "corpus_required": round(corpus_required),
        # Provision + shortfall
        "projected_existing_corpus_fv": round(projected_existing_corpus_fv),
        "total_provision_at_retirement": round(projected_existing_corpus_fv),
        "corpus_shortfall_recurring": round(shortfall_recurring),
        "corpus_shortfall_one_time": round(shortfall_one_time),
        "corpus_shortfall_after_existing": round(total_shortfall),
        # SIP
        "sip_recurring_monthly": round(sip_recurring),
        "sip_one_time_monthly": round(sip_one_time),
        "gross_monthly_sip": round(gross_monthly_sip),
        "ongoing_retirement_sip_monthly": round(ongoing_retirement_sip_monthly),
        "required_monthly_sip": round(required_monthly_sip),
        "computation_trace": trace,
    }


def compute_retirement_stepup(
    *,
    current_age: float,
    retirement_age: float,
    current_corpus_today: float,
    first_year_annual_contribution: float,
    step_up_pct: float,
    rate: float,
    corpus_needed: float,
) -> dict:
    """Excel `Retirement Plan` tab — Section 3 (rows 50-78), the
    "Total Retirement Corpus Calculation (If Step up investments are
    considered)" table.

    Models a client who starts at `first_year_annual_contribution` and steps
    it up `step_up_pct` every year. Each year's contribution is future-valued
    to the retirement date at `rate`; the running total is the corpus the
    plan accumulates. Compared against `corpus_needed` to show surplus / gap.

        J53 = FV(rate, years_to_retire, , −current_corpus)            (one-time)
        G_i = first × (1 + step_up)^i                                (year i contribution)
        J_i = FV(rate, years_to_retire − i, , −G_i)                  (grown to retirement)
        K73 = J53 + Σ J_i                                            (cumulative FV)
        excess = K73 − corpus_needed
    """
    years_to_retire = max(0.0, retirement_age - current_age)
    n = round(years_to_retire)
    rows: list[dict] = []

    # Row 53 — current earmarked corpus grown to retirement.
    fv_corpus = abs(excel_fv(rate, years_to_retire, 0, -current_corpus_today)) if current_corpus_today > 0 else 0.0

    # Closed-form solve: the starting annual contribution that — stepped up at
    # `step_up_pct` and grown to retirement at `rate` — exactly closes the gap
    # left after the current corpus. Each ₹1 of starting contribution grows to
    #   S = Σ_{i=0..n-1} (1+step)^i · (1+rate)^(years_to_retire − i)
    # so required_first = (corpus_needed − fv_corpus) / S.
    step_growth_multiplier = sum(
        ((1 + step_up_pct) ** i) * ((1 + rate) ** (years_to_retire - i))
        for i in range(n)
    )
    gap_after_corpus = max(0.0, corpus_needed - fv_corpus)
    required_first_year = (
        gap_after_corpus / step_growth_multiplier
        if step_growth_multiplier > 0 else 0.0
    )
    cumulative = fv_corpus
    rows.append({
        "label": "Current corpus → FV at retirement",
        "is_one_time": True,
        "years_remaining": round(years_to_retire, 1),
        "age": round(current_age, 1),
        "base_contribution": round(current_corpus_today),
        "step_up_amount": 0,
        "total_contribution": round(current_corpus_today),
        "rate": round(rate, 4),
        "fv_at_retirement": round(fv_corpus),
        "cumulative_fv": round(cumulative),
    })

    # Rows 54-73 — stepped-up annual contributions.
    base = first_year_annual_contribution
    for i in range(n):
        yrs_remaining = years_to_retire - i
        if i == 0:
            step_amt = 0.0
            total = base
        else:
            step_amt = base * step_up_pct
            total = base + step_amt
        fv = abs(excel_fv(rate, yrs_remaining, 0, -total)) if total > 0 else 0.0
        cumulative += fv
        rows.append({
            "label": "Annual contribution (stepped up)",
            "is_one_time": False,
            "year_offset": i,
            "years_remaining": round(yrs_remaining, 1),
            "age": round(current_age + i, 1),
            "base_contribution": round(base),
            "step_up_amount": round(step_amt),
            "total_contribution": round(total),
            "rate": round(rate, 4),
            "fv_at_retirement": round(fv),
            "cumulative_fv": round(cumulative),
        })
        base = total  # next year steps up off this year's total

    excess = cumulative - corpus_needed
    return {
        "step_up_pct": round(step_up_pct, 4),
        "rate": round(rate, 4),
        "first_year_annual_contribution": round(first_year_annual_contribution),
        "first_year_monthly_contribution": round(first_year_annual_contribution / 12),
        "current_corpus_today": round(current_corpus_today),
        "projected_corpus_at_retirement": round(cumulative),
        "corpus_needed": round(corpus_needed),
        "excess_or_gap": round(excess),
        "excess_pct": round(excess / corpus_needed, 4) if corpus_needed else 0.0,
        "reaches_goal": excess >= 0,
        # Solved: the starting SIP that exactly reaches the corpus with this step-up.
        "required_first_year_contribution": round(required_first_year),
        "required_first_year_monthly": round(required_first_year / 12),
        "rows": rows,
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


def _sip_by_purpose(plan: PlanState) -> tuple[float, float, float, bool]:
    """Split monthly SIPs by PURPOSE → (retirement, goal, total, is_explicit).

    Prefers the per-line `recurring_investments` list (which carries the
    "For Retirement" / "For House Purchase" intent). Retirement-purpose SIPs
    are netted against the retirement corpus (Excel E43); goal/general SIPs
    are credited toward financial goals. When no tagged list exists, falls
    back to an instrument heuristic — NPS/PPF/VPF-in-`other` are retirement
    vehicles; MF/RD/direct-equity are goal-directed."""
    ri = plan.recurring_investments or []
    if ri:
        ret = sum(float(r.monthly_amount or 0) for r in ri if r.purpose == "retirement")
        goal = sum(float(r.monthly_amount or 0) for r in ri if r.purpose in ("goal", "general"))
        total = sum(float(r.monthly_amount or 0) for r in ri)
        return ret, goal, total, True
    mi = plan.monthly_investments
    if not mi:
        return 0.0, 0.0, 0.0, False
    ret = float((mi.nps or 0) + (mi.ppf or 0) + (mi.other or 0))
    goal = float((mi.mutual_fund_sip or 0) + (mi.rd or 0) + (mi.direct_equity or 0))
    return ret, goal, ret + goal, False


def _age_from_dob(dob: Optional[str], today: datetime) -> Optional[float]:
    """Fractional age in years from a date-of-birth string. Mirrors the
    firm Excel's `(today − DOB) / 365.25` so ages like 35.79 reconcile to
    the rupee. Accepts ISO (YYYY-MM-DD), DD-MM-YYYY, or DD/MM/YYYY; returns
    None when the date can't be parsed."""
    if not dob:
        return None
    s = str(dob).strip().split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            d = datetime.strptime(s, fmt)
            return max(0.0, (today - d).days / 365.25)
        except ValueError:
            continue
    return None


def _spouse_fractional_age_and_le(
    plan: PlanState, today: datetime
) -> tuple[Optional[float], Optional[int]]:
    """Spouse's fractional age + life expectancy from the second Person row.
    Returns (None, None) when no spouse is recorded so the retirement corpus
    falls back to the self-lifetime horizon."""
    persons = plan.assumptions.persons or []
    if len(persons) < 2:
        return None, None
    spouse = persons[1]
    le = int(spouse.life_expectancy) if spouse.life_expectancy else None
    age = _age_from_dob(spouse.date_of_birth, today)
    return age, le


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
    now = datetime.now()
    current_year = now.year
    retirement_age = pd.retirement_age_target or 60
    life_expectancy = (plan.assumptions.persons[0].life_expectancy if plan.assumptions.persons else 85)
    # Fractional current age from DOB (Excel uses `(today−DOB)/365.25`) so the
    # retirement corpus reconciles to the rupee. Falls back to the integer
    # `fsi.age` when no DOB is on file.
    current_age_frac = _age_from_dob(
        (plan.assumptions.persons[0].date_of_birth if plan.assumptions.persons else None)
        or pd.date_of_birth,
        now,
    )
    current_age = current_age_frac if current_age_frac is not None else float(fsi.age or 30)
    # Calendar year the client retires (used to classify post-retirement goals).
    retirement_year = current_year + round(max(0.0, retirement_age - current_age))

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
    # Non-retirement, one-time goals whose target year falls AT/AFTER the
    # retirement year are post-retirement spends (Excel `Retirement Plan`
    # E26-E29 / `10_Financial_Goals` row 20 — e.g. a legacy gift). They are
    # routed into the retirement corpus (FV + their own SIP) rather than the
    # regular goal-funding list, so they're funded once, not twice.
    post_retirement_one_time: list[Goal] = []
    for g in plan.financial_goals:
        if g.kind == "retirement":
            continue
        if (g.target_year or 0) >= retirement_year:
            post_retirement_one_time.append(g)
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
    # Split SIPs by purpose: only GOAL/general SIPs are credited to goals;
    # retirement-purpose SIPs (NPS/VPF/...) are netted against the retirement
    # corpus instead (below), so neither is double-counted.
    sip_retirement, sip_goal, sip_total, sip_purpose_explicit = _sip_by_purpose(plan)
    existing_sip_for_goals = sip_goal
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
    # Total ongoing SIP (all purposes) — this is what the household's
    # cashflow surplus has to absorb, regardless of which goal it funds.
    existing_sip_monthly = sip_total
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

    # ── Retirement corpus (Excel `Retirement Plan` tab) ───────────────
    # Inputs that mirror the firm's workbook, cell-for-cell:
    #   • discount the corpus annuity at 8.75% (Assumptions E23, conservative)
    #   • fund the SIP at 10.5% (Assumptions E22, hybrid)
    #   • size the horizon to the SPOUSE's lifetime (E14/E15)
    #   • retirement living expense excludes children's school fees (E18)
    #   • add a one-time post-retirement spend (E26-E29) when one is present
    #
    # PLANNED retirement annual expense (E18 in today's rupees): prefer an
    # advisor-entered `kind=retirement` goal target; otherwise derive it
    # from current living expenses MINUS children's school fees (the firm's
    # default — school fees fall away once children are independent).
    retire_goal = next(
        (g for g in plan.financial_goals if g.kind == "retirement" and (g.target_amount or 0) > 0),
        None,
    )
    if retire_goal is not None:
        planned_annual = float(retire_goal.target_amount or 0)
        if retire_goal.is_target_in_today_money:
            retire_annual_expense_today = planned_annual
        else:
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
            {"goal_name": retire_goal.goal_name, "raw_target": planned_annual,
             "is_today_money": retire_goal.is_target_in_today_money},
            round(retire_annual_expense_today),
            unit="INR/yr",
        ))
    else:
        # Excel E18 = (current monthly living expense − children's education) × 12.
        school_fees_monthly = float(plan.monthly_expenses.school_fees or 0)
        retire_monthly = max(0.0, monthly_expenses - school_fees_monthly)
        retire_annual_expense_today = retire_monthly * 12
        trace.append(_trace(
            "Retirement living expense today (current expense − school fees)",
            "(monthly_expenses − school_fees) × 12",
            {"monthly_expenses": round(monthly_expenses),
             "school_fees": round(school_fees_monthly)},
            round(retire_annual_expense_today),
            unit="INR/yr",
        ))

    # Spouse horizon (E14/E15) — present only when a spouse Person is on file.
    spouse_age_frac, spouse_le = _spouse_fractional_age_and_le(plan, now)

    years_to_retire = max(0.0, retirement_age - current_age)
    n_rec = round(years_to_retire)

    # One-time post-retirement spend (E26-E29) from goals routed out above.
    ot_today, ot_years, ot_infl = 0.0, None, None
    if post_retirement_one_time:
        rep = max(post_retirement_one_time, key=lambda g: float(g.target_amount or 0))
        for g in post_retirement_one_time:
            cost = float(g.target_amount or 0)
            if g.is_target_in_today_money is False and g.target_year:
                infl_g = g.inflation_assumed if g.inflation_assumed is not None else (plan.assumptions.inflation or 0.07)
                cost = cost / ((1 + infl_g) ** max(0, g.target_year - current_year))
            ot_today += cost
        ot_years = max(0, (rep.target_year or retirement_year) - current_year)
        ot_infl = rep.inflation_assumed if rep.inflation_assumed is not None else (plan.assumptions.inflation or 0.07)
        trace.append(_trace(
            "Post-retirement one-time spend routed into corpus",
            "Σ today-cost of non-retirement one-time goals with target_year ≥ retirement year",
            {"goals": [g.goal_name for g in post_retirement_one_time],
             "horizon_years": ot_years},
            round(ot_today),
            unit="INR",
        ))

    # Projected corpus from assets LEFT OVER after goal allocation that are
    # retirement-appropriate (EPF / PPF / NPS), grown at the PPF rate (Excel
    # `10_Financial_Goals!I19` = Assumptions E26 = 7.1%). Using the leftover
    # — not the gross holdings — avoids double-counting assets already
    # earmarked to fund the education / house goals above.
    retirement_earmarked_today = float(
        (asset_pool.get("epf", 0) or 0)
        + (asset_pool.get("ppf", 0) or 0)
        + (asset_pool.get("pension", 0) or 0)
    )
    projected_corpus_rate = POST_TAX_RETURN["ppf"]  # 7.1%
    projected_existing_corpus_fv = (
        abs(excel_fv(projected_corpus_rate, n_rec, 0, -retirement_earmarked_today))
        if retirement_earmarked_today > 0 and n_rec > 0 else 0.0
    )

    # Ongoing SIPs already flowing toward RETIREMENT (Excel E43), netted off
    # the gross SIP to give the *additional* monthly commitment. Only
    # retirement-purpose SIPs count here — a SIP earmarked "For House
    # Purchase" must not reduce the retirement ask (see _sip_by_purpose).
    ongoing_retirement_sip = sip_retirement

    retirement = compute_retirement_corpus(
        current_age=current_age,
        retirement_age=retirement_age,
        life_expectancy=life_expectancy,
        retirement_annual_expenses_today=retire_annual_expense_today,
        inflation=plan.assumptions.inflation or 0.07,
        corpus_discount_return=POST_TAX_RETURN["equity_conservative"],  # 8.75% (Assumptions E23)
        spouse_current_age=spouse_age_frac,
        spouse_life_expectancy=spouse_le,
        one_time_spend_today=ot_today,
        one_time_spend_years=ot_years,
        one_time_spend_inflation=ot_infl,
        projected_existing_corpus_fv=projected_existing_corpus_fv,
        sip_funding_return=POST_TAX_RETURN["equity_hybrid"],  # 10.5% (Assumptions E22)
        ongoing_retirement_sip_monthly=ongoing_retirement_sip,
    )
    retirement["used_planned_retirement_expense"] = bool(retire_goal is not None)
    # Back-compat keys the canvas / report still read.
    retirement["existing_retirement_assets_fv"] = round(projected_existing_corpus_fv)
    retirement["existing_retirement_assets_breakdown"] = [
        {"label": bucket.upper(), "today_value": round(asset_pool.get(bucket, 0) or 0)}
        for bucket in ("epf", "ppf", "pension")
        if (asset_pool.get(bucket, 0) or 0) > 0
    ]
    retirement["monthly_sip_committed"] = round(ongoing_retirement_sip)
    retirement["existing_sip_fv_at_retirement"] = 0  # SIPs now netted off the PMT, not FV'd into provision
    # Section-1 extras the firm sheet shows (E17 current living expense, E12 self LE).
    retirement["annual_living_expense_current"] = round(annual_expenses)
    retirement["self_life_expectancy"] = life_expectancy
    # SIP purpose split — how the ongoing-SIP figure was derived.
    retirement["sip_purpose_breakdown"] = {
        "retirement_monthly": round(sip_retirement),
        "goal_monthly": round(sip_goal),
        "total_monthly": round(sip_total),
        "source": "tagged" if sip_purpose_explicit else "instrument_heuristic",
    }

    # ── Retirement Plan §3 — step-up investments table (rows 50-78) ─────
    # Models the client's CURRENT retirement contributions stepped up each
    # year (Excel's F51 default = 10%) and future-valued to retirement. If
    # they have no ongoing retirement SIP, fall back to the level gross SIP
    # so the table still illustrates a reach-the-goal trajectory.
    stepup_rate = plan.assumptions.sip_annual_step_up_pct or 0.10
    first_year_annual = (
        ongoing_retirement_sip * 12 if ongoing_retirement_sip > 0
        else retirement.get("gross_monthly_sip", 0) * 12
    )
    retirement["stepup_plan"] = compute_retirement_stepup(
        current_age=current_age,
        retirement_age=retirement_age,
        current_corpus_today=retirement_earmarked_today,
        first_year_annual_contribution=first_year_annual,
        step_up_pct=stepup_rate,
        rate=POST_TAX_RETURN["equity_hybrid"],  # 10.5% (Assumptions E22)
        corpus_needed=retirement["corpus_required"],
    )

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
        horizon_years=int(min(40, max(life_expectancy - current_age, 10))),
        start_year=current_year,
        start_age=int(round(current_age)),
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
        "current_age": round(current_age, 1),
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
