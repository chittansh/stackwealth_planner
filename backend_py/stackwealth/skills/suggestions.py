"""
Suggestions engine — the AI "how to do better" layer on top of the
Excel-faithful CFP. Where `cfp.py` answers *where the client stands*, this
module answers *how to close the gaps*, using six advisor levers:

    1. Increase the time given to a goal   (guardrailed — see below)
    2. Decrease the goal's value
    3. Increase income
    4. Liquidate hard assets
    5. Lumpsum nudge (a question — never an invented number)
    6. Increase investments (SIP)

The math reuses the exact CFP primitives (`compute_goal_block`,
`compute_retirement_corpus`, `excel_pmt`, `glide_path_return`) so every
suggested number reconciles with the firm's workbook. For each gap we emit
itemised levers AND a single feasible "recommended" combined plan, then
project that plan through the scenario engine to produce a suggested
net-worth / cashflow / retirement snapshot for the canvas overlays.

Subjectivity guardrails (you cannot ask a client to postpone their kid's
education or retire at 80):
    • child_education / child_marriage           → time-LOCKED (no delay)
    • other goals                                → delay ≤ +3 years
    • retirement                                 → delay only up to age 62
    • value cut: essential ≤ 10%, else ≤ 30%
    • liquidation candidates: non-self-occupied real estate + investment gold
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Optional

from ..types import Goal, PlanState
from .cfp import (
    compute_cfp,
    compute_goal_block,
    _build_asset_pool,
)

# ── Guardrails ─────────────────────────────────────────────────────────────
LOCKED_TIME_GOALS: set[str] = {"child_education", "child_marriage"}
GOAL_DELAY_CAP_YEARS: int = 3
RETIREMENT_DELAY_CAP_AGE: int = 62
VALUE_CUT_ESSENTIAL: float = 0.10
VALUE_CUT_DISCRETIONARY: float = 0.30
# Realism caps — a mid-career earner cannot conjure a 50% pay jump. A one-off
# bump (promotion, side income, spouse income) realistically tops out ~10%;
# beyond that the honest move is a step-up commitment, a longer timeline, a
# trimmed target, an asset sale, or a lumpsum — never "grow income 54%".
INCOME_BUMP_CAP_PCT: float = 0.10
# Annual SIP step-up the household commits to as income grows (the realistic
# alternative to a flat, unaffordable level-SIP today).
SIP_STEPUP_PCT: float = 0.10


def _rupees(n: float) -> str:
    return f"₹{round(n):,}"


def _stepup_start_monthly(fv_gap: float, years: int, annual_rate: float,
                          step_up: float = SIP_STEPUP_PCT) -> float:
    """Starting MONTHLY SIP that — stepped up `step_up` each year and grown at
    `annual_rate` — accumulates to `fv_gap` over `years`. Closed form:
        FV = Σ_{i=0..n-1} A·(1+step)^i·(1+rate)^(n-1-i)   (A = first-year annual)
    so A = fv_gap / Σ(...); monthly = A/12. The realistic 'start low, grow with
    income' alternative to a flat level SIP."""
    n = max(1, int(round(years)))
    if fv_gap <= 0 or annual_rate <= 0:
        return 0.0
    mult = sum(((1 + step_up) ** i) * ((1 + annual_rate) ** (n - 1 - i)) for i in range(n))
    if mult <= 0:
        return 0.0
    return (fv_gap / mult) / 12


def _is_essential(goal: Optional[Goal]) -> bool:
    if goal is None:
        return True
    if (goal.kind or "") in LOCKED_TIME_GOALS or goal.kind == "retirement":
        return True
    return (goal.priority or "important") == "essential"


def _liquidation_candidates(plan: PlanState) -> list[dict]:
    """Hard assets that could be sold to fund goals/retirement: real estate
    that is NOT the self-occupied primary home (earmarked, commercial, land,
    or a 2nd+ residential), plus gold held for investment."""
    out: list[dict] = []
    res_seen = 0
    for re in plan.real_estate or []:
        v = float(re.current_value or 0)
        if v <= 0:
            continue
        if re.kind == "residential":
            res_seen += 1
        sellable = (
            re.earmarked_for_sale
            or re.kind in ("commercial", "land", "other")
            or (re.kind == "residential" and res_seen > 1)
        )
        if sellable:
            out.append({"label": re.label or re.kind, "today_value": v, "type": "real_estate"})
    for gd in plan.gold or []:
        if gd.held_for_investment and float(gd.current_value or 0) > 0:
            out.append({"label": gd.label or "Gold", "today_value": float(gd.current_value), "type": "gold"})
    return out


# Realism ordering — lead with what a household can actually do (step up SIPs
# with income, give a flexible goal more time), keep the blunt "add a huge flat
# SIP" and "grow income" toward the end, and push infeasible/locked levers last.
_LEVER_ORDER = {
    "step_up_sip": 0,
    "delay_goal": 1,
    "reduce_value": 2,
    "liquidate_assets": 3,
    "increase_sip": 4,
    "increase_income": 5,
    "lumpsum": 6,
}


def _order_levers(levers: list[dict]) -> list[dict]:
    return sorted(
        levers,
        key=lambda l: (0 if l.get("feasible", True) else 10) + _LEVER_ORDER.get(l.get("lever"), 9),
    )


def _lever(lever: str, title: str, change: str, rationale: str, feasible: bool, impact: dict) -> dict:
    return {
        "lever": lever,
        "title": title,
        "change": change,
        "rationale": rationale,
        "feasible": feasible,
        "impact": impact,
    }


# ── Goal levers ──────────────────────────────────────────────────────────

def _goal_block_for(goal: Goal, current_year: int, asset_pool: dict, *,
                    delay_years: int = 0, value_cut: float = 0.0) -> dict:
    """Re-run a goal's CFP block on a COPY of the goal with a delay and/or
    value-cut applied, against a fresh pool copy (so allocation isn't
    double-spent). Returns the recomputed block."""
    g2 = copy.deepcopy(goal)
    if delay_years and g2.target_year:
        g2.target_year = g2.target_year + delay_years
    if value_cut and g2.target_amount:
        g2.target_amount = g2.target_amount * (1 - value_cut)
    return compute_goal_block(g2, current_year=current_year, asset_pool=copy.deepcopy(asset_pool))


def _goal_levers(goal: Optional[Goal], block: dict, current_year: int,
                 asset_pool: dict, liq: list[dict]) -> list[dict]:
    levers: list[dict] = []
    req = block["required_sip_monthly"]
    existing = block.get("existing_sip_monthly", 0) or 0
    shortfall = max(0.0, req - existing)
    name = block["goal_name"]

    # L6 — increase SIP (always available; the definitional fix)
    levers.append(_lever(
        "increase_sip", "Increase SIP",
        f"Add {_rupees(shortfall)}/mo toward {name}",
        f"Funds {name} fully at the {round(block['effective_return']*100,1)}% glide-path return.",
        True, {"extra_sip_monthly": round(shortfall), "new_sip_monthly": round(req), "funds_goal": True},
    ))

    kind = (goal.kind if goal else "other") or "other"

    # L1 — delay (guardrailed)
    if goal is not None and kind not in LOCKED_TIME_GOALS and (block.get("years_to_go") or 0) > 0:
        nb = _goal_block_for(goal, current_year, asset_pool, delay_years=GOAL_DELAY_CAP_YEARS)
        new_req = nb["required_sip_monthly"]
        levers.append(_lever(
            "delay_goal", "Give it more time",
            f"Delay {name} {GOAL_DELAY_CAP_YEARS}y to {nb['target_year']} → SIP {_rupees(new_req)}/mo",
            f"A longer horizon lets compounding do more of the work, cutting the SIP from {_rupees(req)} to {_rupees(new_req)}.",
            True, {"new_target_year": nb["target_year"], "new_sip_monthly": round(new_req),
                   "sip_saved_monthly": round(max(0, req - new_req))},
        ))
    elif goal is not None and kind in LOCKED_TIME_GOALS:
        levers.append(_lever(
            "delay_goal", "Give it more time", "Not advisable for this goal",
            "Education / marriage timelines are fixed by life events — we don't suggest postponing them.",
            False, {"locked": True},
        ))

    # L2 — decrease value
    if goal is not None and (goal.target_amount or 0) > 0:
        cut = VALUE_CUT_ESSENTIAL if _is_essential(goal) else VALUE_CUT_DISCRETIONARY
        nb = _goal_block_for(goal, current_year, asset_pool, value_cut=cut)
        new_req = nb["required_sip_monthly"]
        levers.append(_lever(
            "reduce_value", "Trim the target",
            f"Reduce {name} by {round(cut*100)}% ({_rupees((goal.target_amount or 0)*cut)} today) → SIP {_rupees(new_req)}/mo",
            f"A {round(cut*100)}% trim ({'essential goal — kept small' if _is_essential(goal) else 'discretionary goal'}) lowers the SIP to {_rupees(new_req)}.",
            True, {"value_cut_pct": cut, "new_sip_monthly": round(new_req),
                   "sip_saved_monthly": round(max(0, req - new_req))},
        ))

    # L4 — liquidate hard assets toward this goal
    if liq:
        total_liq = sum(c["today_value"] for c in liq)
        gap_today = block.get("gap_today") or 0
        applied = min(total_liq, gap_today) if gap_today else 0
        if applied > 0:
            labels = ", ".join(c["label"] for c in liq[:2])
            levers.append(_lever(
                "liquidate_assets", "Liquidate a hard asset",
                f"Direct {_rupees(applied)} from {labels} to {name}",
                "Selling an idle/non-primary asset removes the funding gap without a higher SIP.",
                True, {"liquidate_today": round(applied), "sources": [c["label"] for c in liq]},
            ))

    # L6b — step-up SIP (start lower, grow with income). The realistic
    # alternative to a flat level SIP — what most earners actually do.
    years = block.get("years_to_go") or 0
    fv_gap = block.get("fv_gap") or 0
    if years > 1 and fv_gap > 0:
        start = _stepup_start_monthly(fv_gap, years, block["effective_return"])
        if start > 0 and start < req:
            levers.append(_lever(
                "step_up_sip", "Start lower, step up yearly",
                f"Start at {_rupees(start)}/mo and step up {round(SIP_STEPUP_PCT*100)}%/yr (vs flat {_rupees(req)}/mo)",
                f"As income grows you raise the SIP {round(SIP_STEPUP_PCT*100)}%/yr — so you can begin at {_rupees(start)} now instead of the full {_rupees(req)}, and still reach the goal.",
                True, {"start_sip_monthly": round(start), "step_up_pct": SIP_STEPUP_PCT,
                       "vs_flat_sip_monthly": round(req)},
            ))

    return _order_levers(levers)


# ── Retirement levers (via full re-simulation for consistency) ───────────

def _retire_required_sip(plan: PlanState, *, retirement_age: Optional[int] = None,
                         expense_cut: float = 0.0) -> dict:
    """Re-run compute_cfp on a plan copy with a delayed retirement age and/or
    a trimmed retirement living expense, returning the recomputed retirement
    block. Reuses the exact CFP retirement wiring (spouse horizon, 8.75%
    discount, 10.5% SIP funding, earmarked-asset FV)."""
    p2 = copy.deepcopy(plan)
    if retirement_age is not None:
        p2.personal_details.retirement_age_target = retirement_age
        for per in (p2.assumptions.persons or [])[:1]:
            per.retirement_age = retirement_age
    if expense_cut:
        # Trim current living expense → flows into the retirement expense (E18).
        if p2.freedom_score_inputs.monthly_expenses:
            p2.freedom_score_inputs.monthly_expenses *= (1 - expense_cut)
    return compute_cfp(p2).retirement


def _retirement_levers(plan: PlanState, ret: dict) -> list[dict]:
    levers: list[dict] = []
    req = ret.get("required_monthly_sip", 0) or 0
    name = "retirement corpus"

    # L6 — increase SIP
    levers.append(_lever(
        "increase_sip", "Increase retirement SIP",
        f"Add {_rupees(req)}/mo toward {name}",
        f"Closes the {_rupees(ret.get('corpus_shortfall_after_existing',0))} corpus gap at the 10.5% funding rate.",
        True, {"extra_sip_monthly": round(req), "funds_goal": True},
    ))

    # L1 — delay retirement (capped at 62)
    cur_age = ret.get("retirement_age") or 60
    if cur_age < RETIREMENT_DELAY_CAP_AGE:
        new_age = min(RETIREMENT_DELAY_CAP_AGE, int(round(cur_age)) + GOAL_DELAY_CAP_YEARS)
        if new_age > cur_age:
            nr = _retire_required_sip(plan, retirement_age=new_age)
            new_req = nr.get("required_monthly_sip", 0) or 0
            levers.append(_lever(
                "delay_goal", "Retire a little later",
                f"Retire at {new_age} (not {round(cur_age)}) → SIP {_rupees(new_req)}/mo",
                f"More earning years + fewer drawdown years cut the monthly ask from {_rupees(req)} to {_rupees(new_req)}. Capped at age {RETIREMENT_DELAY_CAP_AGE}.",
                True, {"new_retirement_age": new_age, "new_sip_monthly": round(new_req),
                       "sip_saved_monthly": round(max(0, req - new_req))},
            ))
    else:
        levers.append(_lever(
            "delay_goal", "Retire a little later",
            f"Already at/after age {RETIREMENT_DELAY_CAP_AGE}",
            f"We cap suggested retirement at age {RETIREMENT_DELAY_CAP_AGE} — pushing further isn't a realistic ask.",
            False, {"capped": True},
        ))

    # L2 — trim retirement lifestyle (essential → ≤10%)
    nr = _retire_required_sip(plan, expense_cut=VALUE_CUT_ESSENTIAL)
    new_req = nr.get("required_monthly_sip", 0) or 0
    levers.append(_lever(
        "reduce_value", "Trim retirement lifestyle",
        f"Plan for {round(VALUE_CUT_ESSENTIAL*100)}% lower monthly spend in retirement → SIP {_rupees(new_req)}/mo",
        f"A modestly leaner retirement budget lowers the corpus need and the SIP to {_rupees(new_req)}.",
        True, {"expense_cut_pct": VALUE_CUT_ESSENTIAL, "new_sip_monthly": round(new_req),
               "sip_saved_monthly": round(max(0, req - new_req))},
    ))

    # L4 — reverse mortgage / liquidate a non-primary property
    liq = _liquidation_candidates(plan)
    if liq:
        labels = ", ".join(c["label"] for c in liq[:2])
        total = sum(c["today_value"] for c in liq)
        levers.append(_lever(
            "liquidate_assets", "Use a hard asset for retirement",
            f"Earmark {labels} ({_rupees(total)} today) — sale or reverse mortgage",
            "The firm's plan notes an apartment can back a reverse mortgage after 60; a non-primary property can fund the corpus instead of a higher SIP.",
            True, {"liquidate_today": round(total), "sources": [c["label"] for c in liq]},
        ))

    # L6b — step-up SIP: start lower today, grow with income (from the §3 table).
    sp = ret.get("stepup_plan") or {}
    start = sp.get("required_first_year_monthly", 0) or 0
    if start > 0 and start < req:
        levers.append(_lever(
            "step_up_sip", "Start lower, step up yearly",
            f"Start at {_rupees(start)}/mo and step up {round(SIP_STEPUP_PCT*100)}%/yr (vs flat {_rupees(req)}/mo)",
            f"Stepping the SIP up {round(SIP_STEPUP_PCT*100)}%/yr as income grows lets you begin at {_rupees(start)} now and still reach the corpus.",
            True, {"start_sip_monthly": round(start), "step_up_pct": SIP_STEPUP_PCT,
                   "vs_flat_sip_monthly": round(req)},
        ))
    return _order_levers(levers)


# ── Recommended combined plan ────────────────────────────────────────────

def _build_recommended(plan: PlanState, cfp, surplus: float, current_year: int) -> tuple[dict, dict]:
    """Stack REALISTIC levers a mid-career household can actually execute — in
    small, granular doses rather than one heroic move. Order:
      1) redirect existing free surplus into SIPs,
      2) commit to a 10%/yr SIP step-up (the natural way SIPs grow with income),
      3) delay retirement to the cap (cheap, high-leverage),
      4) push genuinely-flexible (non-locked) shortfall goals out 3 years,
      5) earmark a non-primary hard asset and invest the proceeds (a lumpsum),
      6) a MODEST income lift, capped at +10% (a raise / side income — never 50%).
    Whatever still doesn't fit is reported honestly as a residual + lumpsum nudge
    (computed by the caller from the simulated plan)."""
    ops: list[dict] = []
    summary = cfp.summary
    income = float(summary.get("monthly_income", 0) or 0)
    total_incremental = summary.get("total_incremental_sip_monthly", 0) or 0
    retire_sip = cfp.retirement.get("required_monthly_sip", 0) or 0
    total_ask = total_incremental + retire_sip

    levers_used: list[str] = []
    notes: list[str] = []
    if total_ask <= 0:
        return {"ops": []}, {"summary": "Plan is already on track — keep current SIPs running and step them up with annual income growth.",
                             "levers_used": [], "income_bump_monthly": 0, "surplus_redirected": 0}

    # 1) Redirect the free surplus into SIPs.
    mi = plan.monthly_investments
    base_mf = float((mi.mutual_fund_sip or 0)) if mi else 0.0
    sip_added = min(max(0.0, surplus), total_ask)
    if sip_added > 0:
        ops.append({"path": "monthly_investments.mutual_fund_sip", "op": "set", "value": round(base_mf + sip_added)})
        levers_used.append("increase_sip")
        notes.append(f"Redirect your {_rupees(sip_added)}/mo surplus into SIPs")

    # 2) Commit to a 10%/yr SIP step-up (realistic, income-linked).
    ops.append({"path": "assumptions.sip_annual_step_up_pct", "op": "set", "value": SIP_STEPUP_PCT})
    levers_used.append("step_up_sip")
    notes.append(f"Step up SIPs {round(SIP_STEPUP_PCT*100)}%/yr as income grows")

    # 3) Delay retirement to the cap.
    cur_age = cfp.retirement.get("retirement_age") or 60
    if retire_sip > 0 and cur_age < RETIREMENT_DELAY_CAP_AGE:
        new_age = min(RETIREMENT_DELAY_CAP_AGE, int(round(cur_age)) + GOAL_DELAY_CAP_YEARS)
        ops.append({"path": "personal_details.retirement_age_target", "op": "set", "value": new_age})
        if plan.assumptions.persons:
            ops.append({"path": "assumptions.persons.0.retirement_age", "op": "set", "value": new_age})
        levers_used.append("delay_goal")
        notes.append(f"Retire at {new_age} instead of {round(cur_age)}")

    # 4) Push genuinely-flexible shortfall goals out 3 years (never locked ones).
    short_ids = {b["goal_id"] for b in cfp.goal_blocks if (b.get("sip_shortfall_monthly", 0) or 0) > 0}
    delayed_names: list[str] = []
    for i, g in enumerate(plan.financial_goals):
        if g.id not in short_ids or (g.kind or "") in LOCKED_TIME_GOALS or g.kind == "retirement":
            continue
        if not g.target_year:
            continue
        ops.append({"path": f"financial_goals.{i}.target_year", "op": "set", "value": g.target_year + GOAL_DELAY_CAP_YEARS})
        delayed_names.append(g.goal_name)
    if delayed_names:
        if "delay_goal" not in levers_used:
            levers_used.append("delay_goal")
        notes.append(f"Give {', '.join(delayed_names)} {GOAL_DELAY_CAP_YEARS} more years")

    # 5) Earmark a non-primary hard asset → invest the proceeds (a lumpsum).
    liq = _liquidation_candidates(plan)
    if liq:
        total = sum(c["today_value"] for c in liq)
        labels = ", ".join(c["label"] for c in liq[:2])
        evs = [{"year": current_year + 1, "amount": round(total), "label": "Asset sale (recommended)"}]
        ops.append({"path": "assumptions.lumpsum_events", "op": "set", "value": evs})
        levers_used.append("liquidate_assets")
        notes.append(f"Sell/earmark {labels} (~{_rupees(total)}) and invest the proceeds")

    # 6) A MODEST income lift — capped at +10%. Never the full residual.
    income_bump = 0.0
    if income > 0 and sip_added < total_ask:
        income_bump = round(income * INCOME_BUMP_CAP_PCT)
        ops.append({"path": "freedom_score_inputs.monthly_income", "op": "set", "value": round(income + income_bump)})
        levers_used.append("increase_income")
        notes.append(f"A realistic ~{round(INCOME_BUMP_CAP_PCT*100)}% income lift (+{_rupees(income_bump)}/mo) via a raise or side income")

    human = "; ".join(notes) if notes else "Keep current SIPs running."
    return {"ops": ops}, {
        "summary": human,
        "levers_used": sorted(set(levers_used)),
        "income_bump_monthly": round(income_bump),
        "surplus_redirected": round(sip_added),
    }


# ── Public entrypoint ────────────────────────────────────────────────────

def compute_suggestions(plan: PlanState) -> dict:
    from .scenario import simulate_mutation  # local import avoids cycle

    current_year = datetime.now().year
    cfp = compute_cfp(plan)
    summary = cfp.summary
    surplus = float(summary.get("affordable_new_sip_monthly", 0) or 0)

    asset_pool = _build_asset_pool(plan)
    liq = _liquidation_candidates(plan)
    goals_by_id = {g.id: g for g in plan.financial_goals}

    # ── Goals domain ──────────────────────────────────────────────────
    goal_rows: list[dict] = []
    for b in cfp.goal_blocks:
        req = b["required_sip_monthly"]
        funded_pct = b.get("funded_share_at_affordable_sip")
        shortfall = b.get("sip_shortfall_monthly", 0) or 0
        if shortfall <= 0 and (req - (b.get("existing_sip_monthly", 0) or 0)) <= 0:
            continue
        g = goals_by_id.get(b["goal_id"])
        goal_rows.append({
            "goal_name": b["goal_name"],
            "target_year": b["target_year"],
            "required_sip_monthly": round(req),
            "existing_sip_monthly": round(b.get("existing_sip_monthly", 0) or 0),
            "shortfall_monthly": round(shortfall),
            "funded_pct": round((funded_pct or 0) * 100, 1) if funded_pct is not None else None,
            "levers": _goal_levers(g, b, current_year, asset_pool, liq),
        })

    # ── Retirement domain ─────────────────────────────────────────────
    # Fulfilment is judged the way the firm's sheet does it — via the STEP-UP
    # plan (Section 3): does the current retirement contribution, stepped up
    # 10%/yr, plus the earmarked corpus, reach what's needed? The flat level-SIP
    # figure is kept as a conservative alternative, not the verdict.
    ret = cfp.retirement
    ret_shortfall = ret.get("corpus_shortfall_after_existing", 0) or 0
    ret_required = ret.get("required_monthly_sip", 0) or 0          # flat level SIP (conservative)
    corpus_req = ret.get("corpus_required", 0) or 0
    provisioned = ret.get("projected_existing_corpus_fv", 0) or 0
    ongoing_ret_sip = ret.get("ongoing_retirement_sip_monthly", 0) or 0
    stepup_reaches = bool(ret.get("stepup_reaches_goal"))
    stepup_funded = ret.get("stepup_funded_pct")
    stepup_start_req = ret.get("stepup_required_start_sip_monthly", 0) or 0   # starting SIP to reach via step-up
    stepup_additional = ret.get("stepup_additional_start_sip_monthly", 0) or 0  # extra over current, stepped up
    ret_levers = _retirement_levers(plan, ret) if not stepup_reaches else []
    retirement_dom = {
        "title": "Suggested Retirement Glide",
        "corpus_required": round(corpus_req),
        "provisioned": round(provisioned),
        "shortfall": round(ret_shortfall),
        # step-up verdict (primary)
        "funded_pct": stepup_funded if stepup_funded is not None else (round((provisioned / corpus_req) * 100, 1) if corpus_req else 100.0),
        "on_track": stepup_reaches,
        "stepup_reaches_goal": stepup_reaches,
        "stepup_required_start_sip_monthly": round(stepup_start_req),
        "stepup_additional_start_sip_monthly": round(stepup_additional),
        # flat level-SIP alternative (conservative)
        "required_sip_monthly": round(ret_required),
        "ongoing_sip_monthly": round(ongoing_ret_sip),
        "levers": ret_levers,
    }

    # Retirement is a GOAL too — surface it in Suggested Goals (only when the
    # step-up trajectory does NOT already reach it), with the SIPs already
    # flowing to it credited and the realistic step-up starting SIP as the ask.
    if not stepup_reaches:
        retire_year = current_year + round(ret.get("years_to_retire", 0) or 0)
        goal_rows.insert(0, {
            "goal_name": "Retirement",
            "target_year": retire_year,
            "is_retirement": True,
            "via_stepup": True,
            "required_sip_monthly": round(stepup_start_req),   # step-up STARTING SIP to reach
            "existing_sip_monthly": round(ongoing_ret_sip),
            "shortfall_monthly": round(stepup_additional),     # extra to add to the starting SIP
            "funded_pct": stepup_funded,
            "levers": ret_levers,
        })

    # ── Cashflow domain ───────────────────────────────────────────────
    total_incremental = summary.get("total_incremental_sip_monthly", 0) or 0
    sip_shortfall = summary.get("sip_surplus_shortfall_monthly", 0) or 0
    income = summary.get("monthly_income", 0) or 0
    cashflow_levers: list[dict] = []
    if sip_shortfall > 0 and income > 0:
        # Realistic income lift — capped at +10%. We DON'T suggest closing the
        # whole gap with income (a 50% raise isn't a real lever); we show what a
        # plausible raise covers, then point to the other levers for the rest.
        bump = min(income * INCOME_BUMP_CAP_PCT, sip_shortfall)
        pct = round((bump / income) * 100, 1)
        covers_all = bump >= sip_shortfall - 1
        cashflow_levers.append(_lever(
            "increase_income", "Increase income (realistically)",
            f"A ~{pct}% lift (+{_rupees(bump)}/mo) via a raise or side income "
            + ("covers the gap" if covers_all else f"covers {_rupees(bump)} of the {_rupees(sip_shortfall)}/mo gap"),
            "A mid-career raise / side income / spouse income realistically adds up to ~10%. Beyond that, lean on the step-up SIP, a longer timeline, a trimmed goal, or an asset sale — not an unrealistic pay jump.",
            True, {"income_increase_monthly": round(bump), "income_increase_pct": pct,
                   "covers_full_gap": covers_all, "remaining_gap_monthly": round(max(0, sip_shortfall - bump))},
        ))
        cashflow_levers.append(_lever(
            "step_up_sip", "Step up SIPs every year",
            f"Commit to raising SIPs {round(SIP_STEPUP_PCT*100)}%/yr as income grows",
            "Stepping up with income lets you start lower today and still reach the goals — the realistic alternative to a flat, unaffordable SIP now.",
            True, {"step_up_pct": SIP_STEPUP_PCT},
        ))
    cashflow_dom = {
        "title": "Suggested Cashflow",
        "monthly_surplus": round(summary.get("monthly_surplus_pre_sip", 0) or 0),
        "monthly_existing_sip": round(summary.get("monthly_existing_sip", 0) or 0),
        "affordable_new_sip": round(surplus),
        "total_required_incremental_sip": round(total_incremental),
        "sip_shortfall_monthly": round(sip_shortfall),
        "is_affordable": sip_shortfall <= 0,
        "levers": cashflow_levers,
    }

    # ── Recommended combined plan + projection ────────────────────────
    rec_mutation, rec_meta = _build_recommended(plan, cfp, surplus, current_year)
    baseline_headline = plan.computed.headline_amount_at_horizon or 0
    baseline_series = [
        {"year": p.year, "value": p.value} for p in (plan.computed.net_worth_series or [])
    ]
    # Net worth at the RETIREMENT year is the decision-relevant impact metric —
    # far more credible than the age-85 horizon, where decades of step-up
    # compound to absurd magnitudes.
    retire_year = current_year + round(ret.get("years_to_retire", 0) or 0)

    def _nw_at(series: list[dict], year: int) -> float:
        if not series:
            return 0.0
        at = next((p for p in series if p.get("year") == year), None)
        return float((at or series[-1]).get("value", 0) or 0)

    baseline_nw_retire = _nw_at(baseline_series, retire_year)
    suggested = {}
    residual_note = None
    try:
        comp = simulate_mutation(plan, rec_mutation)
        sug_cfp = comp.get("cfp") or {}
        sug_ret = sug_cfp.get("retirement") or {}
        sug_summary = sug_cfp.get("summary") or {}
        sug_corpus = sug_ret.get("corpus_required", 0) or 0
        sug_prov = (sug_ret.get("projected_existing_corpus_fv", 0) or 0)
        sug_series = comp.get("net_worth_series", [])
        suggested_nw_retire = _nw_at(sug_series, retire_year)
        suggested = {
            "net_worth_series": sug_series,
            "headline_at_horizon": comp.get("headline_amount_at_horizon", 0),
            "net_worth_at_retirement": round(suggested_nw_retire),
            "retirement_required_sip": round(sug_ret.get("required_monthly_sip", 0) or 0),
            "retirement_funded_pct": round((sug_prov / sug_corpus) * 100, 1) if sug_corpus else 100.0,
        }
        # Honest residual AFTER the recommended plan, on a conservative level-SIP
        # basis. The step-up commitment narrows this over time, but we surface
        # it so the plan isn't oversold.
        residual = (sug_summary.get("total_incremental_sip_monthly", 0) or 0) + (sug_ret.get("required_monthly_sip", 0) or 0)
        if residual > 1000:
            residual_note = (
                f"On a conservative flat-SIP basis about {_rupees(residual)}/mo is still uncovered "
                "(the 10%/yr step-up above narrows this as income grows). To fully close it, extend a "
                "timeline further, trim a discretionary goal, or fold in a lumpsum (see the prompt below)."
            )
    except Exception as e:  # projection must never break the suggestions payload
        suggested = {"error": str(e), "net_worth_series": baseline_series}

    nw_retire_delta = (suggested.get("net_worth_at_retirement", baseline_nw_retire) or 0) - baseline_nw_retire

    recommended = {
        **rec_meta,
        "mutation": rec_mutation,
        "residual_note": residual_note,
        "impact": {
            "retirement_year": retire_year,
            "net_worth_at_retirement": suggested.get("net_worth_at_retirement"),
            "baseline_net_worth_at_retirement": round(baseline_nw_retire),
            "net_worth_at_retirement_delta": round(nw_retire_delta),
            # kept for back-compat / secondary display
            "headline_at_horizon": suggested.get("headline_at_horizon"),
            "headline_delta": round((suggested.get("headline_at_horizon", baseline_headline) or 0) - baseline_headline),
        },
    }

    # A gap exists if any goal is short, retirement's step-up trajectory does
    # NOT reach the corpus, or the SIPs already exceed monthly surplus.
    has_gaps = bool(goal_rows) or (not stepup_reaches) or sip_shortfall > 0

    return {
        "generated_at": datetime.now().isoformat(),
        "has_gaps": has_gaps,
        "guardrails": {
            "locked_time_goals": sorted(LOCKED_TIME_GOALS),
            "goal_delay_cap_years": GOAL_DELAY_CAP_YEARS,
            "retirement_delay_cap_age": RETIREMENT_DELAY_CAP_AGE,
            "value_cut_essential": VALUE_CUT_ESSENTIAL,
            "value_cut_discretionary": VALUE_CUT_DISCRETIONARY,
        },
        "recommended": recommended,
        "domains": {
            "cashflow": cashflow_dom,
            "goals": {"title": "Suggested Goals", "goals": goal_rows},
            "retirement": retirement_dom,
        },
        "nudges": [{
            "lever": "lumpsum",
            "title": "Any lumpsum on the horizon?",
            "question": "Is a one-time inflow expected — bonus, ESOP vesting, property/asset sale, inheritance, or maturing investments? Even a partial lumpsum can cut the required SIPs materially. If so, tell me the amount and rough year and I'll fold it in.",
        }],
        "suggested": suggested,
    }
