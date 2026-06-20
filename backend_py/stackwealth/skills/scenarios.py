"""
Scenario Engine — the core IP of the AI Financial Plan (per
`AI_Financial_Plan_Developer_Brief.docx`, §6). Given the baseline plan it:

  1. Derives the INVESTABLE SURPLUS (§6.1) — net income minus essential +
     discretionary expenses, EMIs, insurance premiums, and the emergency-fund
     build SIP.
  2. Computes the total additional SIP needed across all goals + retirement.
  3. Produces a constructive VERDICT + 4-tier confidence (§6.1 / Table 11).
  4. If the plan is achievable → a single optimised plan (§6.2).
     If there's a shortfall → two distinct paths, EASY and AGGRESSIVE
     (Table 9 / §6.5), built from the six levers (§6.3) within the hard
     subjectivity rules (§6.4 / §11): retirement ≤ 65; never delay child
     education / marriage / parent-medical; never cut a goal below 30%;
     emergency fund never reduced; liquidation last; income nudge-only.

All math reuses the Excel-faithful primitives (cfp.py) and the scenario
projector (scenario.simulate_mutation), so every number reconciles with the
workbook. Tone is constructive — forbidden client-facing words are stripped.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Optional

from ..types import Goal, PlanState
from .cfp import compute_cfp
from .suggestions import (
    LOCKED_TIME_GOALS,
    SIP_STEPUP_PCT,
    _liquidation_candidates,
    _rupees,
    _stepup_start_monthly,
)

# ── Guardrails reconciled to the brief (§6.4 / §11) ─────────────────────────
RETIREMENT_CAP_AGE = 65                     # brief: never push retirement past 65
GOAL_DELAY_CAP_YEARS = 5                    # House/Retirement up to 5y; others bounded
GOAL_REDUCTION_FLOOR = 0.30                 # never reduce a goal below 30% of original
EASY_STEPUP = 0.12                          # Easy path nudges step-up 10% → 12%
AGGRESSIVE_STEPUP = 0.15                    # Aggressive path 10% → 15%
INCOME_BUMP_CAP_PCT = 0.10                  # income lever is a capped nudge

# Words that must never reach the client (§11). Replaced with calm phrasing.
_FORBIDDEN = {
    "failure": "shortfall", "disaster": "gap", "too late": "still time",
    "impossible": "challenging", "crisis": "gap", "dangerously short": "below target",
    "underprepared": "still building", "you cannot afford": "this stretches the budget",
}


def _compact(n: float) -> str:
    """₹ in Cr / L for readability on large figures."""
    n = round(n)
    if abs(n) >= 1_00_00_000:
        return f"₹{n / 1_00_00_000:.2f} Cr"
    if abs(n) >= 1_00_000:
        return f"₹{n / 1_00_000:.1f} L"
    return _rupees(n)


def _constructive(text: str) -> str:
    out = text
    for bad, good in _FORBIDDEN.items():
        out = out.replace(bad, good).replace(bad.capitalize(), good.capitalize())
    return out


# ── Investable surplus (§6.1) ───────────────────────────────────────────────

def compute_investable_surplus(plan: PlanState, cfp) -> dict:
    """Net income − essential − discretionary − EMIs − insurance premiums −
    emergency-fund build SIP. Insurance premium already sits inside the
    living-expense aggregate, so we subtract the EF build SIP on top of the
    engine's pre-SIP surplus."""
    s = cfp.summary
    income = float(s.get("monthly_income", 0) or 0)
    gross_surplus = float(s.get("monthly_surplus_pre_sip", 0) or 0)  # income − expenses − EMI

    me = plan.monthly_expenses
    essential = sum(float(getattr(me, k) or 0) for k in (
        "household_expenses", "rent_or_emi", "groceries", "utilities",
        "school_fees", "insurance_premium", "medical")) or float(s.get("monthly_expenses", 0) or 0)
    emi = float(s.get("monthly_emi", 0) or 0)
    bare_minimum = essential + emi  # excludes SIPs + discretionary (§6.1)

    ef = plan.emergency_fund
    ef_current = float((ef.total_emergency_corpus if ef else 0) or 0)
    ef_target = 6 * bare_minimum
    ef_gap = max(0.0, ef_target - ef_current)
    ef_build_sip = round(ef_gap / 36) if ef_gap > 0 and bare_minimum > 0 else 0  # 36-month build

    investable = max(0.0, gross_surplus - ef_build_sip)
    return {
        "monthly_income": round(income),
        "gross_surplus": round(gross_surplus),
        "bare_minimum_expense": round(bare_minimum),
        "emergency_target": round(ef_target),
        "emergency_current": round(ef_current),
        "emergency_build_sip": ef_build_sip,
        "investable_surplus": round(investable),
    }


# ── Verdict + confidence (Table 11) ─────────────────────────────────────────

def _verdict(investable: float, total_needed: float, retire_age: int) -> dict:
    if total_needed <= 0:
        return {"confidence": "High", "achievable": True,
                "text": "Your goals and retirement are fully funded by what's already running — you're on track with room to spare."}
    ratio = investable / total_needed
    gap = max(0.0, total_needed - investable)
    if investable >= total_needed * 1.20:
        return {"confidence": "High", "achievable": True,
                "text": _constructive(f"You're on track to fund every one of your goals and retire at {retire_age}, with a comfortable cushion on top.")}
    if investable >= total_needed:
        return {"confidence": "Medium", "achievable": True,
                "text": _constructive(f"You're on track to fund every goal on the current plan and retire at {retire_age}. The plan runs tight, so a few simple moves will give you a healthier cushion.")}
    if gap <= total_needed * 0.20:
        return {"confidence": "Low", "achievable": False,
                "text": _constructive(f"On your current trajectory, your essential goals are funded. The fuller plan needs roughly {_rupees(round(gap, -2))}/month more — three constructive paths to get there are in the Scenarios section, and they all start from where you are today.")}
    return {"confidence": "Very Low", "achievable": False,
            "text": _constructive(f"On your current trajectory, there's real work to do to bring your full plan within reach. The gap is roughly {_rupees(round(gap, -2))}/month — three paths forward, each realistic in different ways, are in the Scenarios section, and they all start from where you are today.")}


# ── Lever application helpers (build a ScenarioMutation) ─────────────────────

def _is_year_flexible(g: Goal) -> bool:
    """Year-fixed: child education/marriage, parent medical. Everything else
    can be delayed within bounds."""
    kind = (g.kind or "").lower()
    name = (g.goal_name or "").lower()
    if kind in LOCKED_TIME_GOALS or kind == "retirement":
        return False
    if "parent" in name and ("medical" in name or "surgery" in name):
        return False
    return True


def _is_amount_flexible(g: Goal) -> bool:
    """Amount-fixed: emergency fund only. Reduction order handled by caller."""
    name = (g.goal_name or "").lower()
    return "emergency" not in name


def _reduction_rank(g: Goal) -> int:
    """Lower = reduce first: discretionary/lifestyle → child marriage → child
    education (§6.4)."""
    kind = (g.kind or "").lower()
    if kind in ("foreign_travel", "other", "house_purchase"):
        return 0
    if kind == "child_marriage":
        return 1
    if kind == "child_education":
        return 2
    return 0


def _apply_overrides(plan: PlanState, overrides: Optional[dict]) -> PlanState:
    """RM 'additional inputs' (Scenarios page) reshape the BASELINE plan before
    the engine runs, so the scenarios build on top of them. Supports: expected
    lumpsum (amount+year), income increase %, SIP step-up %, and per-goal
    delay-years / reduce-% (within guardrails — child goals never delayed,
    no goal cut below 30%, retirement never past 65)."""
    if not overrides:
        return plan
    p = copy.deepcopy(plan)
    inc = float(overrides.get("income_increase_pct") or 0)
    if inc and p.freedom_score_inputs.monthly_income:
        p.freedom_score_inputs.monthly_income = round(p.freedom_score_inputs.monthly_income * (1 + inc / 100))
    step = overrides.get("step_up_pct")
    if step is not None:
        p.assumptions.sip_annual_step_up_pct = float(step) / 100 if float(step) > 1 else float(step)
    lump_amt = float(overrides.get("lumpsum_amount") or 0)
    lump_yr = int(overrides.get("lumpsum_year") or 0)
    if lump_amt > 0 and lump_yr > 0:
        p.assumptions.lumpsum_events = list(p.assumptions.lumpsum_events or []) + [
            type(p.assumptions.lumpsum_events[0])(year=lump_yr, amount=lump_amt, label="Expected lumpsum (RM)")
            if p.assumptions.lumpsum_events else __import__("stackwealth.types", fromlist=["LumpsumEvent"]).LumpsumEvent(year=lump_yr, amount=lump_amt, label="Expected lumpsum (RM)")
        ]
    goal_ovr = overrides.get("goal_overrides") or {}
    for g in p.financial_goals:
        ov = goal_ovr.get(g.id) or goal_ovr.get(g.goal_name)
        if not ov:
            continue
        delay = int(ov.get("delay_years") or 0)
        if delay and g.target_year and (g.kind or "") not in LOCKED_TIME_GOALS and g.kind != "retirement":
            g.target_year += min(delay, GOAL_DELAY_CAP_YEARS)
        red = float(ov.get("reduce_pct") or 0)
        if red and g.target_amount and "emergency" not in (g.goal_name or "").lower():
            g.target_amount = round(g.target_amount * (1 - min(red, 1 - GOAL_REDUCTION_FLOOR) / 100)) if red > 1 else round(g.target_amount * (1 - min(red, 1 - GOAL_REDUCTION_FLOOR)))
    return p


def _stepup_funded(sug_cfp: dict, sug_ret: dict, step_up_rate: float, investable: float) -> dict:
    """Achievement on the step-up basis — the realistic 'start lower, grow with
    income' funding. For each goal we compute the STARTING monthly SIP that,
    stepped up `step_up_rate`/yr, reaches its remaining gap by its (possibly
    delayed/reduced) target year; sum with the retirement step-up start. The
    plan is achieved when the investable surplus covers that total. Responds to
    every lever: step-up rate ↓, delays ↓, reductions ↓, income ↑ surplus."""
    goal_start = 0.0
    for b in sug_cfp.get("goal_blocks", []):
        gap = b.get("fv_gap", 0) or 0
        yrs = b.get("years_to_go", 0) or 0
        r = b.get("effective_return", 0.105) or 0.105
        if gap > 0 and yrs > 0:
            goal_start += _stepup_start_monthly(gap, yrs, r, step_up_rate)
    retire_start = sug_ret.get("stepup_additional_start_sip_monthly", 0) or 0
    total_start = goal_start + retire_start
    funded_pct = round(min(100.0, investable / total_start * 100)) if total_start > 0 else 100
    achieved = total_start <= 0 or investable >= total_start * 0.99
    return {"funded_pct": funded_pct, "achieved": achieved, "total_start_needed": round(total_start),
            "goal_start_needed": round(goal_start), "retire_start_needed": round(retire_start)}


def compute_scenarios(plan: PlanState, overrides: Optional[dict] = None) -> dict:
    from .scenario import simulate_mutation  # local import avoids cycle

    plan = _apply_overrides(plan, overrides)
    cfp = compute_cfp(plan)
    s = cfp.summary
    ret = cfp.retirement
    current_year = datetime.now().year

    surplus_blk = compute_investable_surplus(plan, cfp)
    investable = float(surplus_blk["investable_surplus"])

    goal_incremental = float(s.get("total_incremental_sip_monthly", 0) or 0)
    retire_required = float(ret.get("required_monthly_sip", 0) or 0)
    total_needed = goal_incremental + retire_required
    retire_age = int(ret.get("retirement_age", 60) or 60)

    verdict = _verdict(investable, total_needed, retire_age)

    # Net-worth + corpus reference for the baseline.
    baseline_series = [{"year": p.year, "value": p.value} for p in (plan.computed.net_worth_series or [])]
    retire_year = current_year + round(ret.get("years_to_retire", 0) or 0)

    def _nw_at(series, year):
        m = next((p for p in series if p.get("year") == year), None)
        return float((m or (series[-1] if series else {})).get("value", 0) or 0)

    corpus_required = float(ret.get("corpus_required", 0) or 0)

    # ── Top-3 actions (§7, Table 10-D) ────────────────────────────────────
    top_actions = _top_actions(plan, cfp, surplus_blk, verdict["achievable"])

    # ── Goals that the scenarios can flex ─────────────────────────────────
    goals_by_id = {g.id: g for g in plan.financial_goals}
    short_goal_ids = [b["goal_id"] for b in cfp.goal_blocks if (b.get("sip_shortfall_monthly", 0) or 0) > 0]

    existing_sip = float(s.get("monthly_existing_sip", 0) or 0)
    baseline_scenario = {
        "key": "baseline",
        "name": "Baseline — current trajectory",
        "headline": _constructive(verdict["text"]),
        "levers": [],
        # Monthly SIP = what's actually being invested today (no new commitment).
        "monthly_sip": round(existing_sip),
        "total_sip_needed": round(total_needed),
        "retirement_age": retire_age,
        # Retirement corpus on the step-up basis — same metric the scenarios use,
        # so the comparison is consistent and bounded (not the full net worth,
        # which over-compounds across the horizon).
        "retirement_corpus": round((ret.get("stepup_plan") or {}).get("projected_corpus_at_retirement", 0) or 0),
        "corpus_required": round(corpus_required),
        "net_worth_series": baseline_series,
        "goals_met_pct": round(min(100.0, (investable / total_needed * 100) if total_needed else 100.0)),
        "trade_off": "No changes to your life — but the fuller plan stays partly unfunded." if not verdict["achievable"] else "No changes needed; keep the current SIPs running.",
    }

    result = {
        "generated_at": datetime.now().isoformat(),
        "as_of_year": current_year,
        "surplus": surplus_blk,
        "total_sip_needed": round(total_needed),
        "goal_sip_needed": round(goal_incremental),
        "retirement_sip_needed": round(retire_required),
        "verdict": verdict,
        "top_actions": top_actions,
        "achievable": verdict["achievable"],
        "baseline": baseline_scenario,
    }

    if verdict["achievable"]:
        # §6.2 — single optimised plan.
        result["single_plan"] = {
            "headline": _constructive(
                f"One plan funds everything: deploy {_rupees(round(total_needed))}/mo across your goals "
                f"(you have {_rupees(round(investable))}/mo of investable surplus), and step SIPs up "
                f"{round(SIP_STEPUP_PCT*100)}%/yr with income. The cushion goes to a larger retirement buffer."),
            "monthly_sip": round(total_needed),
            "cushion_monthly": round(max(0.0, investable - total_needed)),
            "step_up_pct": SIP_STEPUP_PCT,
        }
        result["scenarios"] = [baseline_scenario]
        result["which_path"] = []
        return result

    # ── §6.5 — Easy + Aggressive paths ────────────────────────────────────
    easy = _build_scenario(
        plan, cfp, simulate_mutation, key="easy", name="Easy Path — least disruption",
        step_up=EASY_STEPUP, delay_flexible=True, allow_liquidation=False,
        goals_by_id=goals_by_id, short_goal_ids=short_goal_ids, surplus_blk=surplus_blk,
        current_year=current_year, retire_year=retire_year, retire_age=retire_age,
        corpus_required=corpus_required, total_needed=total_needed, investable=investable,
    )
    aggressive = _build_scenario(
        plan, cfp, simulate_mutation, key="aggressive", name="Aggressive Path — maximum cushion",
        step_up=AGGRESSIVE_STEPUP, delay_flexible=False, allow_liquidation=True,
        goals_by_id=goals_by_id, short_goal_ids=short_goal_ids, surplus_blk=surplus_blk,
        current_year=current_year, retire_year=retire_year, retire_age=retire_age,
        corpus_required=corpus_required, total_needed=total_needed, investable=investable,
    )

    result["scenarios"] = [baseline_scenario, easy, aggressive]
    result["comparison"] = _comparison(baseline_scenario, easy, aggressive)
    result["which_path"] = [
        {"path": "Easy Path", "suits": "You value stability and a predictable lifestyle. You're willing to let a discretionary goal (a holiday, a car, a home upgrade) move out a couple of years so your essential goals and retirement stay fully on track without raising your monthly commitment much."},
        {"path": "Aggressive Path", "suits": "You want maximum certainty and a bigger retirement cushion, and you're comfortable with a higher savings rate now (and, if needed, putting an idle asset to work). You keep every goal on its original date."},
        {"path": "Baseline", "suits": "You'd rather change nothing today and revisit at your next annual review — accepting that the fuller plan stays partly unfunded until then."},
    ]
    return result


def _build_scenario(plan, cfp, simulate_mutation, *, key, name, step_up, delay_flexible,
                    allow_liquidation, goals_by_id, short_goal_ids, surplus_blk,
                    current_year, retire_year, retire_age, corpus_required, total_needed, investable) -> dict:
    """Construct one path's mutation from the levers, project it, and summarise."""
    ops: list[dict] = []
    levers: list[str] = []

    # Lever 1 — step-up SIP commitment.
    ops.append({"path": "assumptions.sip_annual_step_up_pct", "op": "set", "value": step_up})
    levers.append(f"Step up SIPs to {round(step_up*100)}%/yr (from the default {round(SIP_STEPUP_PCT*100)}%)")

    # Lever 6/deploy — put the full investable surplus to work as SIP.
    mi = plan.monthly_investments
    base_mf = float((mi.mutual_fund_sip or 0)) if mi else 0.0
    deploy = round(investable)
    if deploy > 0:
        ops.append({"path": "monthly_investments.mutual_fund_sip", "op": "set", "value": round(base_mf + deploy)})
        levers.append(f"Direct your full investable surplus ({_rupees(deploy)}/mo) into goal SIPs")

    # Aggressive path also leans on a realistic income lift (≤10%).
    if key == "aggressive":
        income = float((plan.freedom_score_inputs.monthly_income or 0))
        bump = round(income * INCOME_BUMP_CAP_PCT)
        if bump > 0:
            ops.append({"path": "freedom_score_inputs.monthly_income", "op": "set", "value": round(income + bump)})
            levers.append(f"A realistic ~{round(INCOME_BUMP_CAP_PCT*100)}% income lift (+{_rupees(bump)}/mo) via a raise or side income")

    delayed_names: list[str] = []
    if delay_flexible:
        # Lever 2 — give year-flexible shortfall goals more time (Easy path
        # leans on this to stay 'least disruption' while closing the gap).
        for i, g in enumerate(plan.financial_goals):
            if g.id not in short_goal_ids or not _is_year_flexible(g) or not g.target_year:
                continue
            delay = GOAL_DELAY_CAP_YEARS
            ops.append({"path": f"financial_goals.{i}.target_year", "op": "set", "value": g.target_year + delay})
            delayed_names.append(f"{g.goal_name} → {g.target_year + delay}")
        if delayed_names:
            levers.append("Give flexible goals more time: " + ", ".join(delayed_names))

    # Lever 5 — asset liquidation (last resort; Aggressive only).
    liquidated = []
    if allow_liquidation:
        liq = _liquidation_candidates(plan)
        if liq:
            total_liq = sum(c["today_value"] for c in liq)
            ops.append({"path": "assumptions.lumpsum_events", "op": "set",
                        "value": [{"year": current_year + 1, "amount": round(total_liq), "label": "Asset put to work (scenario)"}]})
            liquidated = [c["label"] for c in liq]
            levers.append("Put an idle/non-primary asset to work: " + ", ".join(liquidated) + f" (~{_compact(total_liq)})")

    # Project.
    comp = simulate_mutation(plan, {"ops": ops})
    sug_cfp = comp.get("cfp") or {}
    sug_ret = sug_cfp.get("retirement") or {}
    sug_summary = sug_cfp.get("summary") or {}
    series = comp.get("net_worth_series", [])

    def _nw_at(year):
        m = next((p for p in series if p.get("year") == year), None)
        return float((m or (series[-1] if series else {})).get("value", 0) or 0)

    # Achievement on the STEP-UP basis (responds to step-up rate, delays,
    # reductions, income, lumpsum) — the realistic 'start lower, grow with
    # income' funding the levers actually deliver.
    fund = _stepup_funded(sug_cfp, sug_ret, step_up, investable)
    goals_met_pct = fund["funded_pct"]
    achieved = fund["achieved"]
    # Monthly SIP = total monthly investment commitment under this path: the
    # full investable surplus deployed (+ the income lift for Aggressive). This
    # rises across Baseline → Easy → Aggressive (more commitment, more cushion).
    income = float((plan.freedom_score_inputs.monthly_income or 0))
    income_bump = round(income * INCOME_BUMP_CAP_PCT) if key == "aggressive" else 0
    monthly_sip = round(investable) + income_bump

    # Per-goal outcomes (step-up basis).
    outcomes = []
    for b in sug_cfp.get("goal_blocks", []):
        g = goals_by_id.get(b.get("goal_id"))
        delayed = g and any((g.goal_name or "") in d for d in delayed_names)
        gap = b.get("fv_gap", 0) or 0
        if gap <= 0:
            status = "Met in full"
        elif achieved and delayed:
            status = f"Met — date moved to {b.get('target_year')}"
        elif achieved:
            status = "Met in full"
        else:
            start_g = _stepup_start_monthly(gap, b.get("years_to_go", 0) or 0, b.get("effective_return", 0.105) or 0.105, step_up)
            status = f"Start ~{_rupees(start_g)}/mo (stepped up) to fund"
        outcomes.append({"goal": b.get("goal_name"), "target_year": b.get("target_year"), "status": status})

    # Retirement corpus on the step-up basis (rises with the path's step-up
    # rate) — same metric as the baseline, bounded and consistent.
    corpus_at_retire = (sug_ret.get("stepup_plan") or {}).get("projected_corpus_at_retirement", 0) or _nw_at(retire_year)
    trade_off = (
        "Your essential goals and retirement stay on track; a flexible goal or two simply moves out a little."
        if key == "easy" else
        "Every goal stays on its original date and your retirement cushion is largest — in exchange for the highest savings discipline now."
    )

    return {
        "key": key,
        "name": name,
        "headline": _scenario_headline(key, retire_age, delayed_names, liquidated, step_up),
        "levers": levers,
        "monthly_sip": monthly_sip,
        "total_sip_needed": round(total_needed),
        "retirement_age": retire_age,
        "retirement_corpus": round(corpus_at_retire),
        "corpus_required": round(corpus_required),
        "goals_met_pct": goals_met_pct,
        "achieved": achieved,
        "outcomes": outcomes,
        "net_worth_series": series,
        "trade_off": _constructive(trade_off),
    }


def _scenario_headline(key, retire_age, delayed_names, liquidated, step_up) -> str:
    if key == "easy":
        bits = [f"step up SIPs to {round(step_up*100)}%/yr"]
        if delayed_names:
            bits.append(f"move {len(delayed_names)} flexible goal{'s' if len(delayed_names) > 1 else ''} out a couple of years")
        return _constructive("Easy Path: " + ", ".join(bits) + f", retire at {retire_age}.")
    bits = [f"step up SIPs to {round(step_up*100)}%/yr", "keep every goal on its original date"]
    if liquidated:
        bits.append("put an idle asset to work")
    return _constructive("Aggressive Path: " + ", ".join(bits) + f", retire at {retire_age}.")


def _comparison(baseline, easy, aggressive) -> list[dict]:
    rows = [
        ("Monthly SIP", "monthly_sip", "money"),
        ("Goals funded", "goals_met_pct", "pct"),
        ("Retirement age", "retirement_age", "age"),
        ("Retirement corpus", "retirement_corpus", "money"),
    ]
    out = []
    for label, k, kind in rows:
        out.append({
            "metric": label, "kind": kind,
            "baseline": baseline.get(k), "easy": easy.get(k), "aggressive": aggressive.get(k),
        })
    out.append({"metric": "Biggest trade-off", "kind": "text",
                "baseline": baseline.get("trade_off"), "easy": easy.get("trade_off"), "aggressive": aggressive.get("trade_off")})
    return out


def _top_actions(plan, cfp, surplus_blk, achievable) -> list[str]:
    """Top-3 highest-impact actions (Table 10-D). Protection-first when on
    track; gap-closing levers when short."""
    actions: list[str] = []
    ins = cfp.insurance or {}
    add_term = ins.get("additional_cover_required", 0) or 0
    if add_term > 0:
        actions.append(_constructive(f"Add about {_compact(add_term)} of term life cover — it protects the whole plan if anything happens to the earner."))
    ef = surplus_blk
    if ef["emergency_current"] < ef["emergency_target"]:
        actions.append(_constructive(f"Build your emergency fund to {_compact(ef['emergency_target'])} ({_rupees(ef['emergency_build_sip'])}/mo into a liquid fund) before ramping other SIPs."))
    if not achievable:
        actions.append("Pick a path in the Scenarios section — each one closes the gap a different way (more SIP, a little more time, or a trimmed discretionary goal).")
    else:
        actions.append(_constructive(f"Step up your SIPs {round(SIP_STEPUP_PCT*100)}%/yr with each salary increment to widen the retirement cushion."))
    # Pad to 3.
    if len(actions) < 3:
        actions.append("Review the plan every April — step up SIPs, rebalance, and re-run as income and goals change.")
    return actions[:3]
