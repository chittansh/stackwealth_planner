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


def _rupees(n: float) -> str:
    return f"₹{round(n):,}"


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

    return levers


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
    return levers


# ── Recommended combined plan ────────────────────────────────────────────

def _build_recommended(plan: PlanState, cfp, surplus: float) -> tuple[dict, dict]:
    """Stack feasible levers into one plan that the household can actually
    execute. Priority: spend available surplus on SIP first; if that doesn't
    cover the total ask, lean on allowed delays + bounded trims + the income
    lever for the residual. Returns (mutation, human_summary)."""
    ops: list[dict] = []
    summary = cfp.summary
    total_incremental = summary.get("total_incremental_sip_monthly", 0) or 0
    retire_sip = cfp.retirement.get("required_monthly_sip", 0) or 0
    total_ask = total_incremental + retire_sip

    levers_used: list[str] = []
    notes: list[str] = []

    # 1) Put the available surplus to work as extra SIP.
    mi = plan.monthly_investments
    base_mf = float((mi.mutual_fund_sip or 0)) if mi else 0.0
    sip_added = min(max(0.0, surplus), total_ask)
    if sip_added > 0:
        ops.append({"path": "monthly_investments.mutual_fund_sip", "op": "set",
                    "value": round(base_mf + sip_added)})
        levers_used.append("increase_sip")
        notes.append(f"Deploy your {_rupees(sip_added)}/mo free surplus as SIP")

    residual = max(0.0, total_ask - sip_added)

    # 2) Residual → delay retirement to the cap (cheap, high-leverage) + income lever.
    if residual > 0:
        cur_age = cfp.retirement.get("retirement_age") or 60
        if cur_age < RETIREMENT_DELAY_CAP_AGE:
            new_age = min(RETIREMENT_DELAY_CAP_AGE, int(round(cur_age)) + GOAL_DELAY_CAP_YEARS)
            ops.append({"path": "personal_details.retirement_age_target", "op": "set", "value": new_age})
            if plan.assumptions.persons:
                ops.append({"path": "assumptions.persons.0.retirement_age", "op": "set", "value": new_age})
            levers_used.append("delay_goal")
            notes.append(f"Retire at {new_age} instead of {round(cur_age)}")

        # Income lever for whatever still doesn't fit.
        income = summary.get("monthly_income", 0) or 0
        if income > 0:
            needed_income = income + residual
            pct = round((residual / income) * 100, 1)
            ops.append({"path": "freedom_score_inputs.monthly_income", "op": "set",
                        "value": round(needed_income)})
            levers_used.append("increase_income")
            notes.append(f"Grow income ~{pct}% (+{_rupees(residual)}/mo) — raise, side income, or spouse income")

    human = "; ".join(notes) if notes else "Plan is already on track — keep current SIPs running."
    return {"ops": ops}, {"summary": human, "levers_used": sorted(set(levers_used))}


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
    ret = cfp.retirement
    ret_shortfall = ret.get("corpus_shortfall_after_existing", 0) or 0
    ret_required = ret.get("required_monthly_sip", 0) or 0
    corpus_req = ret.get("corpus_required", 0) or 0
    provisioned = ret.get("projected_existing_corpus_fv", 0) or 0
    retirement_dom = {
        "title": "Suggested Retirement Glide",
        "corpus_required": round(corpus_req),
        "provisioned": round(provisioned),
        "shortfall": round(ret_shortfall),
        "required_sip_monthly": round(ret_required),
        "funded_pct": round((provisioned / corpus_req) * 100, 1) if corpus_req else 100.0,
        "levers": _retirement_levers(plan, ret) if ret_required > 0 else [],
        "on_track": ret_required <= 0,
    }

    # ── Cashflow domain ───────────────────────────────────────────────
    total_incremental = summary.get("total_incremental_sip_monthly", 0) or 0
    sip_shortfall = summary.get("sip_surplus_shortfall_monthly", 0) or 0
    income = summary.get("monthly_income", 0) or 0
    cashflow_levers: list[dict] = []
    if sip_shortfall > 0 and income > 0:
        pct = round((sip_shortfall / income) * 100, 1)
        cashflow_levers.append(_lever(
            "increase_income", "Increase income",
            f"Grow income ~{pct}% (+{_rupees(sip_shortfall)}/mo) to fund every goal's SIP",
            "The required SIPs exceed your monthly surplus; closing it needs either more income or trimmed goals.",
            True, {"income_increase_monthly": round(sip_shortfall), "income_increase_pct": pct},
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
    rec_mutation, rec_meta = _build_recommended(plan, cfp, surplus)
    baseline_headline = plan.computed.headline_amount_at_horizon or 0
    baseline_series = [
        {"year": p.year, "value": p.value} for p in (plan.computed.net_worth_series or [])
    ]
    suggested = {}
    try:
        comp = simulate_mutation(plan, rec_mutation)
        sug_cfp = comp.get("cfp") or {}
        sug_ret = sug_cfp.get("retirement") or {}
        sug_corpus = sug_ret.get("corpus_required", 0) or 0
        sug_prov = (sug_ret.get("projected_existing_corpus_fv", 0) or 0)
        suggested = {
            "net_worth_series": comp.get("net_worth_series", []),
            "headline_at_horizon": comp.get("headline_amount_at_horizon", 0),
            "retirement_required_sip": round(sug_ret.get("required_monthly_sip", 0) or 0),
            "retirement_funded_pct": round((sug_prov / sug_corpus) * 100, 1) if sug_corpus else 100.0,
        }
    except Exception as e:  # projection must never break the suggestions payload
        suggested = {"error": str(e), "net_worth_series": baseline_series}

    headline_delta = (suggested.get("headline_at_horizon", baseline_headline) or 0) - baseline_headline

    recommended = {
        **rec_meta,
        "mutation": rec_mutation,
        "impact": {
            "headline_at_horizon": suggested.get("headline_at_horizon"),
            "headline_delta": round(headline_delta),
            "baseline_headline": round(baseline_headline),
        },
    }

    has_gaps = bool(goal_rows) or ret_required > 0 or sip_shortfall > 0

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
