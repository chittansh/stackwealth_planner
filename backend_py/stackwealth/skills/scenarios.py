"""
Scenario Engine — the core IP of the AI Financial Plan (per
`AI_Financial_Plan_Developer_Brief.docx`, §6). Given the baseline plan it:

  1. Runs the BASELINE (§6.1) — investable surplus vs total SIP required across
     all goals + retirement → ACHIEVABLE / SHORTFALL verdict + confidence.
  2. If achievable → a single optimised plan (§6.2).
  3. If a shortfall → THREE constructive paths (§6.5), each sized to fund 100%
     of stated goals using the eight levers (§6.3) within the hard subjectivity
     rules (§6.4):
        Path 1 — Reducing Expectations  (delay/trim flexible goals, modest step-up)
        Path 2 — Stretching Ourselves   (aggressive step-up, lumpsum, income nudge,
                                         higher-risk equity — keep every goal)
        Path 3 — Balanced               (a moderate blend of every lever)

Levers: 1 step-up SIP, 2 delay goal, 3 reduce goal, 4 lumpsum, 5 asset
liquidation (last resort), 6 income nudge, 7 expense optimisation, 8 higher-risk
equity (Hybrid 10.5% → Aggressive 12.25% for goals ≥ 10y; with a non-skippable
mismatch caution when the client's risk profile is Conservative).

All math reuses the Excel-faithful primitives (cfp.py) and the step-up SIP
closed form (suggestions._stepup_start_monthly), so every number reconciles with
the workbook. Tone is constructive — forbidden client-facing words are stripped.
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

# ── Returns (cfp post-tax) — lever 8 swaps Hybrid → Aggressive ───────────────
HYBRID_RETURN = 0.105
AGGRESSIVE_RETURN = 0.1225

# ── Guardrails (§6.4) ────────────────────────────────────────────────────────
RETIREMENT_CAP_AGE = 65
GOAL_DELAY_CAP_YEARS = 5          # House/Retirement up to 5y (others bounded too)
GOAL_REDUCTION_FLOOR = 0.30       # never reduce a goal below 30% of original
EQUITY_MIN_HORIZON = 10           # lever 8 only for goals ≥ 10y
INCOME_NUDGE_FLAG_PCT = 0.25      # income nudge above this share of income → advisor note

# Per-path SIP step-up rate (lever 1).
PATH1_STEPUP = 0.12
PATH2_STEPUP = 0.15
PATH3_STEPUP = 0.12

# Words that must never reach the client (§11). Replaced with calm phrasing.
_FORBIDDEN = {
    "failure": "shortfall", "disaster": "gap", "too late": "still time",
    "impossible": "challenging", "crisis": "gap", "dangerously short": "below target",
    "underprepared": "still building", "you cannot afford": "this stretches the budget",
}

# Lever-8 mismatch caution — exact phrasing pattern from the brief (§6.3). Shown
# inline beside the lever every time it is used with a Conservative profile.
LEVER8_CAUTION = (
    "Heads up — this path uses higher-risk equity (Aggressive, 12.25% post-tax "
    "projection) for your long-horizon money. This doesn't match your current risk "
    "profile of Conservative. It can work, and the math closes your gap, but it means "
    "sharper short-term swings: your portfolio may fall 25–35% in a bad year and take "
    "2–3 years to recover. If that discomfort would be real for you, you have two "
    "options — pick Path 1 or Path 3 which don't lean on this lever, or talk to your "
    "Stack Wealth advisor about whether your risk tolerance has shifted enough to "
    "formally update your profile."
)
LEVER8_DEFAULT = "Your long-horizon money working harder — comes with sharper short-term swings."


def _compact(n: float) -> str:
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


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _r500(x: float) -> int:
    return int(round(x / 500.0) * 500)


# ── Investable surplus (§6.1) ───────────────────────────────────────────────

def compute_investable_surplus(plan: PlanState, cfp) -> dict:
    """Net income − essential − discretionary − EMIs − insurance premiums −
    emergency-fund build SIP (if EF < 6× bare-minimum expense)."""
    s = cfp.summary
    income = float(s.get("monthly_income", 0) or 0)
    gross_surplus = float(s.get("monthly_surplus_pre_sip", 0) or 0)  # income − expenses − EMI

    me = plan.monthly_expenses
    essential = sum(float(getattr(me, k) or 0) for k in (
        "household_expenses", "rent_or_emi", "groceries", "utilities",
        "school_fees", "insurance_premium", "medical")) or float(s.get("monthly_expenses", 0) or 0)
    emi = float(s.get("monthly_emi", 0) or 0)
    bare_minimum = essential + emi

    ef = plan.emergency_fund
    ef_current = float((ef.total_emergency_corpus if ef else 0) or 0)
    ef_target = 6 * bare_minimum
    ef_gap = max(0.0, ef_target - ef_current)
    ef_build_sip = round(ef_gap / 36) if ef_gap > 0 and bare_minimum > 0 else 0

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


def _discretionary_monthly(plan: PlanState, cfp) -> float:
    """Spend the AI may optimise (lever 7): total monthly expenses minus the
    untouchables (groceries, utilities, school fees, medical, EMI, insurance)."""
    me = plan.monthly_expenses
    total = float(cfp.summary.get("monthly_expenses", 0) or 0)
    locked = sum(float(getattr(me, k) or 0) for k in (
        "groceries", "utilities", "school_fees", "medical", "insurance_premium", "rent_or_emi"))
    return max(0.0, total - locked)


# ── Verdict + confidence (Table 11) ─────────────────────────────────────────

def _verdict(investable: float, total_needed: float, retire_age: int) -> dict:
    if total_needed <= 0:
        return {"confidence": "High", "achievable": True,
                "text": "Your goals and retirement are fully funded by what's already running — you're on track with room to spare."}
    gap = max(0.0, total_needed - investable)
    if investable >= total_needed * 1.20:
        return {"confidence": "High", "achievable": True,
                "text": _constructive(f"You're on track to fund every one of your goals and retire at {retire_age}, with a comfortable cushion on top.")}
    if investable >= total_needed:
        return {"confidence": "Medium", "achievable": True,
                "text": _constructive(f"You're on track to fund every goal on the current plan and retire at {retire_age}. The plan runs tight, so a few simple moves will give you a healthier cushion.")}
    if gap <= total_needed * 0.20:
        return {"confidence": "Low", "achievable": False,
                "text": _constructive(f"Your essential goals are funded. The fuller plan needs roughly {_rupees(round(gap, -2))}/month more — the three paths below each fund 100% of your goals a different way, and they all start from where you are today.")}
    return {"confidence": "Very Low", "achievable": False,
            "text": _constructive(f"There's real work to bring the full plan within reach — the gap is roughly {_rupees(round(gap, -2))}/month. The three paths below each fund 100% of your goals a different way, and they all start from where you are today.")}


# ── Risk profile (for lever-8 caution) ──────────────────────────────────────

def _risk_label(plan: PlanState) -> Optional[str]:
    rp = plan.computed.risk_profile
    if not rp:
        return None
    return (getattr(rp, "recommended_profile", "") or "").strip() or None


def _is_conservative(plan: PlanState) -> bool:
    lbl = _risk_label(plan)
    return bool(lbl) and "conservative" in lbl.lower()


# ── Goal / retirement state model (for analytic lever sizing) ───────────────

def _goal_states(plan: PlanState, cfp) -> list[dict]:
    by_id = {g.id: g for g in plan.financial_goals}
    idx_by_id = {g.id: i for i, g in enumerate(plan.financial_goals)}
    out = []
    for b in cfp.goal_blocks:
        gid = b.get("goal_id")
        g = by_id.get(gid)
        fv = float(b.get("future_value_needed", 0) or 0)
        gap = float(b.get("fv_gap", 0) or 0)
        out.append({
            "id": gid, "idx": idx_by_id.get(gid),
            "name": b.get("goal_name") or "Goal",
            "kind": ((g.kind if g else "") or "").lower(),
            "yrs": int(round(b.get("years_to_go", 0) or 0)),
            "ret": float(b.get("effective_return", HYBRID_RETURN) or HYBRID_RETURN),
            "fv_needed": fv, "fv_allocated": max(0.0, fv - gap), "gap": gap,
            "today_cost": float(b.get("today_cost", 0) or 0),
            "orig_today_cost": float(b.get("today_cost", 0) or 0),
            "target_year": b.get("target_year"), "orig_year": b.get("target_year"),
            "delay": 0, "reduce": 0.0, "equity": False,
        })
    return out


def _retire_state(ret: dict) -> dict:
    return {
        "gap": float(ret.get("corpus_shortfall_after_existing", ret.get("corpus_required", 0)) or 0),
        "yrs": int(round(ret.get("years_to_retire", 0) or 0)),
        "ret": float(ret.get("sip_funding_return", HYBRID_RETURN) or HYBRID_RETURN),
        "corpus_required": float(ret.get("corpus_required", 0) or 0),
        "equity": False,
    }


def _start(gap: float, yrs: int, ret: float, step_up: float) -> float:
    return _stepup_start_monthly(gap, yrs, ret, step_up) if (gap > 0 and yrs > 0) else 0.0


def _eff_ret(item: dict) -> float:
    return AGGRESSIVE_RETURN if (item.get("equity") and item["yrs"] >= EQUITY_MIN_HORIZON) else item["ret"]


def _required_start(states: list[dict], retire: dict, step_up: float) -> float:
    tot = sum(_start(s["gap"], s["yrs"], _eff_ret(s), step_up) for s in states)
    tot += _start(retire["gap"], retire["yrs"], _eff_ret(retire), step_up)
    return tot


def _stepup_fv(monthly_start: float, years: int, rate: float, step_up: float) -> float:
    """Forward FV of a starting monthly SIP stepped up `step_up`/yr — the inverse
    of `_stepup_start_monthly`."""
    n = max(1, int(round(years)))
    if monthly_start <= 0 or rate <= 0:
        return 0.0
    A = monthly_start * 12
    return sum(A * ((1 + step_up) ** i) * ((1 + rate) ** (n - 1 - i)) for i in range(n))


def _retire_corpus(retire: dict, required_start: float, available: float, step_up: float) -> int:
    """Projected retirement corpus consistent with the analytic funding verdict.
    When achieved, the retirement gap is funded; the CUSHION emerges from the
    path's own levers — a SIP sized to just fund the gap at the baseline (hybrid,
    10% step-up) is then grown at THIS path's step-up rate and (lever 8) return,
    so aggressive paths overshoot the target and modest paths land near it
    (matches the brief's ordering). When short, the corpus scales with the
    funded fraction so the % reads consistently."""
    need = retire["corpus_required"]
    gap = retire["gap"]
    if required_start > available * 1.001:
        frac = available / required_start if required_start > 0 else 1.0
        return round(need * frac)
    funded_existing = max(0.0, need - gap)
    base_start = _start(gap, retire["yrs"], retire["ret"], SIP_STEPUP_PCT)
    fv = _stepup_fv(base_start, retire["yrs"], _eff_ret(retire), step_up)
    return round(funded_existing + fv)


# ── Lever appliers (mutate state dicts in place) ────────────────────────────

def _year_flexible(s: dict) -> bool:
    kind, name = s["kind"], (s["name"] or "").lower()
    if kind in LOCKED_TIME_GOALS:
        return False
    if "parent" in name and ("medical" in name or "surgery" in name):
        return False
    return True


def _reducible(s: dict) -> bool:
    return "emergency" not in (s["name"] or "").lower()


def _reduce_rank(s: dict) -> int:
    kind = s["kind"]
    if kind == "child_marriage":
        return 1
    if kind == "child_education":
        return 2
    return 0  # discretionary / lifestyle first


def _do_delay(s: dict, years: int) -> None:
    d = min(years, GOAL_DELAY_CAP_YEARS)
    s["delay"] = d
    s["yrs"] = (s["orig_year"] - datetime.now().year) + d if s["orig_year"] else s["yrs"] + d
    s["yrs"] = max(1, s["yrs"])
    if s["orig_year"]:
        s["target_year"] = s["orig_year"] + d


def _do_reduce(s: dict, pct: float) -> None:
    pct = min(pct, 1 - GOAL_REDUCTION_FLOOR)
    s["reduce"] = pct
    new_fv = s["fv_needed"] * (1 - pct)
    s["gap"] = max(0.0, new_fv - s["fv_allocated"])
    s["today_cost"] = s["orig_today_cost"] * (1 - pct)


def _do_equity(states: list[dict], retire: dict) -> bool:
    used = False
    for s in states:
        if s["gap"] > 0 and s["yrs"] >= EQUITY_MIN_HORIZON:
            s["equity"] = True
            used = True
    if retire["gap"] > 0 and retire["yrs"] >= EQUITY_MIN_HORIZON:
        retire["equity"] = True
        used = True
    return used


def _apply_lumpsum(states: list[dict], retire: dict, amount: float) -> None:
    """Apply a one-time lumpsum to the largest-gap item — it grows at that
    item's return to the goal date, shrinking the FV gap."""
    pool = [("retire", retire)] + [("goal", s) for s in states]
    pool = [(t, it) for t, it in pool if it["gap"] > 0]
    if not pool or amount <= 0:
        return
    _, target = max(pool, key=lambda ti: ti[1]["gap"])
    grown = amount * ((1 + _eff_ret(target)) ** max(1, target["yrs"]))
    target["gap"] = max(0.0, target["gap"] - grown)


def _lumpsum_pool(plan: PlanState, surplus_blk: dict) -> dict:
    """Lever 4 — expected/idle money beyond the emergency reserve."""
    fsi = plan.freedom_score_inputs
    liquid = float(getattr(fsi, "liquid_assets_current_value", 0) or 0)
    idle = max(0.0, liquid - float(surplus_blk["emergency_target"]))
    cur_year = datetime.now().year
    expected = sum(
        float(e.amount or 0) for e in (plan.assumptions.lumpsum_events or [])
        if (e.year or 0) > cur_year and (e.amount or 0) > 0
    )
    return {"idle": round(idle), "expected": round(expected), "total": round(idle + expected)}


# ── RM overrides (Scenarios page "additional inputs") ───────────────────────

def _apply_overrides(plan: PlanState, overrides: Optional[dict]) -> PlanState:
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
        from ..types import LumpsumEvent
        p.assumptions.lumpsum_events = list(p.assumptions.lumpsum_events or []) + [
            LumpsumEvent(year=lump_yr, amount=lump_amt, label="Expected lumpsum (RM)")
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
            frac = red / 100 if red > 1 else red
            g.target_amount = round(g.target_amount * (1 - min(frac, 1 - GOAL_REDUCTION_FLOOR)))
    return p


# ── Trajectory + projected corpus per path (grounded via simulate) ──────────

def _project_series(plan: PlanState, simulate_mutation, *, step_up, deploy, income_bump,
                    delays: list[tuple[int, int]], reductions: list[tuple[int, float]],
                    lumpsum_amt: float) -> list[dict]:
    """Run one mutation purely to get a net-worth trajectory whose SHAPE
    reflects this path's lever choices (the headline corpus/funding numbers come
    from the analytic step-up model, which is the funding source of truth)."""
    ops: list[dict] = [{"path": "assumptions.sip_annual_step_up_pct", "op": "set", "value": step_up}]
    mi = plan.monthly_investments
    base_mf = float((mi.mutual_fund_sip or 0)) if mi else 0.0
    if deploy > 0:
        ops.append({"path": "monthly_investments.mutual_fund_sip", "op": "set", "value": round(base_mf + deploy)})
    if income_bump > 0 and plan.freedom_score_inputs.monthly_income:
        ops.append({"path": "freedom_score_inputs.monthly_income", "op": "set",
                    "value": round(plan.freedom_score_inputs.monthly_income + income_bump)})
    for idx, yr in delays:
        if idx is not None:
            ops.append({"path": f"financial_goals.{idx}.target_year", "op": "set", "value": yr})
    for idx, amt in reductions:
        if idx is not None:
            ops.append({"path": f"financial_goals.{idx}.target_amount", "op": "set", "value": round(amt)})
    if lumpsum_amt > 0:
        cur = datetime.now().year
        ops.append({"path": "assumptions.lumpsum_events", "op": "set",
                    "value": [{"year": cur + 1, "amount": round(lumpsum_amt), "label": "Committed lumpsum (scenario)"}]})
    comp = simulate_mutation(plan, {"ops": ops})
    return comp.get("net_worth_series", []) or []


# ── Per-goal outcomes ("what this funds" — the structural anchor) ────────────

def _outcomes(states: list[dict], retire: dict, achieved: bool, funded_pct: int) -> list[dict]:
    out = []
    for s in states:
        parts = []
        if s["delay"]:
            parts.append(f"moved to {s['target_year']}")
        if s["reduce"] > 0.001:
            parts.append(f"budget {_compact(s['orig_today_cost'])}→{_compact(s['today_cost'])} (today)")
        adj = f" ({', '.join(parts)})" if parts else ""
        if achieved:
            status = ("Met in full" + adj) if parts else f"Met in full at original year & amount"
        else:
            status = _constructive(f"Lands at ~{funded_pct}% — book an advisor session to close the rest")
        out.append({"goal": s["name"], "target_year": s["target_year"], "status": status})
    # Retirement line.
    need = retire["corpus_required"]
    proj = retire.get("projected_corpus", 0) or 0
    pct = round(proj / need * 100) if need else 100
    cushion = proj - need
    if proj >= need:
        rstatus = f"Corpus {_compact(proj)} — meets {_compact(need)} target ({_compact(cushion)} cushion)"
    else:
        rstatus = f"Corpus {_compact(proj)} vs {_compact(need)} target ({pct}%)"
    out.append({"goal": "Retirement", "target_year": retire.get("target_year"), "status": rstatus})
    return out


# ── Path builders ───────────────────────────────────────────────────────────

def _close_with_reductions(states, retire, step_up, available) -> list[dict]:
    """Apply lever 3 in the prescribed order/bands until funded or floor hit."""
    reduced: list[dict] = []
    if _required_start(states, retire, step_up) <= available:
        return reduced
    for s in sorted([x for x in states if _reducible(x) and x["gap"] > 0], key=_reduce_rank):
        for band in (0.10, 0.20, 0.30):
            _do_reduce(s, band)
            if _required_start(states, retire, step_up) <= available:
                break
        reduced.append(s)
        if _required_start(states, retire, step_up) <= available:
            break
    return reduced


def _path1(plan, states, retire, surplus_blk, discretionary, simulate) -> dict:
    investable = float(surplus_blk["investable_surplus"])
    step = PATH1_STEPUP
    levers = [{"text": f"SIP step-up {_pct(SIP_STEPUP_PCT)}/yr → {_pct(step)}/yr (modest)"}]

    expense_opt = _r500(min(0.10 * discretionary, 8000)) if discretionary > 1000 else 0
    available = investable + expense_opt

    # Lever 2 — give year-flexible goals more time (up to the 5y cap).
    delayed = []
    for s in states:
        if s["gap"] > 0 and _year_flexible(s) and s["yrs"] > 0:
            _do_delay(s, GOAL_DELAY_CAP_YEARS)
            delayed.append(s)
    if delayed:
        levers.append({"text": "Move flexible goals out: " + ", ".join(
            f"{s['name']} {s['orig_year']}→{s['target_year']}" for s in delayed)})

    # Lever 3 — reduce in order if still short.
    reduced = _close_with_reductions(states, retire, step, available)
    for s in reduced:
        levers.append({"text": _constructive(
            f"Trim {s['name']} {_pct(s['reduce'])}: {_compact(s['orig_today_cost'])} → {_compact(s['today_cost'])} (today's value) — "
            f"{_compact(s['today_cost'])} still funds a meaningful version of this goal")})

    if expense_opt > 0:
        levers.append({"text": f"Find ~{_rupees(expense_opt)}/mo from discretionary spend (light — not required to close the gap)"})

    required = _required_start(states, retire, step)
    funded_pct = round(min(100.0, available / required * 100)) if required > 0 else 100
    achieved = required <= available * 1.001

    corpus = _retire_corpus(retire, required, available, step)
    retire["projected_corpus"] = corpus
    retire["target_year"] = datetime.now().year + retire["yrs"]
    series = _project_series(plan, simulate, step_up=step, deploy=investable, income_bump=0,
                             delays=[(s["idx"], s["target_year"]) for s in delayed],
                             reductions=[(s["idx"], s["today_cost"]) for s in reduced], lumpsum_amt=0)

    return {
        "key": "path1", "name": "Path 1 — Reducing Expectations",
        "headline": _constructive("Your essentials run untouched; your lifestyle goals move out and scale down to fit today's capacity."),
        "levers": levers, "caution": None,
        "monthly_sip": round(min(required, available)), "retirement_age": _retire_age(retire),
        "retirement_corpus": corpus, "corpus_required": round(retire["corpus_required"]),
        "goals_met_pct": 100 if achieved else funded_pct, "achieved": achieved,
        "outcomes": _outcomes(states, retire, achieved, funded_pct),
        "net_worth_series": series,
        "advisor_note": None if achieved else _constructive(
            "Even on this path the full plan lands a little short — please book a session with your Stack Wealth advisor to close the rest."),
        "trade_off": _constructive("The least disruption to your savings rate and income. The plan bends to fit you — a couple of lifestyle goals shift out and scale down; children and retirement stay untouched."),
    }


def _path2(plan, states, retire, surplus_blk, discretionary, simulate) -> dict:
    investable = float(surplus_blk["investable_surplus"])
    income = float(plan.freedom_score_inputs.monthly_income or 0)
    conservative = _is_conservative(plan)
    step = PATH2_STEPUP
    levers = [{"text": f"SIP step-up {_pct(SIP_STEPUP_PCT)}/yr → {_pct(step)}/yr (aggressive)"}]

    # Lever 4 — commit expected/idle lumpsums to the largest goal.
    pool = _lumpsum_pool(plan, surplus_blk)
    lump = float(pool["total"])
    if lump > 0:
        _apply_lumpsum(states, retire, lump)
        src = []
        if pool["idle"] > 0:
            src.append(f"{_compact(pool['idle'])} idle cash beyond your emergency reserve")
        if pool["expected"] > 0:
            src.append(f"{_compact(pool['expected'])} expected one-time inflows")
        levers.append({"text": "Commit lumpsums to your largest goal: " + " + ".join(src) + f" (~{_compact(lump)})"})
    else:
        levers.append({"text": "Do you expect any large one-time inflow (bonus, RSU vesting, inheritance, property sale)? Committing it here would close more of the gap."})

    # Lever 7 — recurring expense optimisation (larger band).
    expense_opt = _r500(min(0.25 * discretionary, 25000)) if discretionary > 1000 else 0
    if expense_opt > 0:
        levers.append({"text": f"Find ~{_rupees(expense_opt)}/mo from current discretionary spend"})

    # Lever 8 — higher-risk equity for long-horizon money.
    if _do_equity(states, retire):
        levers.append({"text": "Higher-risk equity for goals ≥ 10 years away: Hybrid (10.5% post-tax) → Aggressive (12.25% post-tax). "
                               + (LEVER8_CAUTION if conservative else LEVER8_DEFAULT),
                       "lever8": True})

    available = investable + expense_opt
    required = _required_start(states, retire, step)
    # Lever 6 — income nudge closes any residual (keeps every goal at original
    # year & amount, per Path 2's contract).
    residual = max(0.0, required - available)
    income_nudge = round(residual)
    if income_nudge > 0:
        levers.append({"text": _constructive(
            f"If your household income rises by about {_rupees(income_nudge)}/month — consistent with normal career growth — this path funds every goal at its original year and amount. Worth a conversation about career growth or additional income streams.")})
    available += residual
    achieved = True  # income nudge absorbs the residual by construction

    advisor_note = None
    if income and income_nudge > income * INCOME_NUDGE_FLAG_PCT:
        advisor_note = _constructive(
            f"The income lift this path leans on ({_rupees(income_nudge)}/mo) is sizable — if that isn't realistic, please book a session with your Stack Wealth advisor to weigh Path 1 or 3.")

    corpus = _retire_corpus(retire, required, available, step)
    retire["projected_corpus"] = corpus
    retire["target_year"] = datetime.now().year + retire["yrs"]
    series = _project_series(plan, simulate, step_up=step, deploy=investable, income_bump=income_nudge,
                             delays=[], reductions=[], lumpsum_amt=lump)

    return {
        "key": "path2", "name": "Path 2 — Stretching Ourselves",
        "headline": _constructive("Every goal funded as originally planned — at the original year and the original amount. It asks more of your savings discipline, your bonuses, and your tolerance for market swings."),
        "levers": levers, "caution": LEVER8_CAUTION if conservative else None,
        "monthly_sip": round(required), "retirement_age": _retire_age(retire),
        "retirement_corpus": corpus, "corpus_required": round(retire["corpus_required"]),
        "goals_met_pct": 100, "achieved": achieved,
        "outcomes": _outcomes(states, retire, True, 100),
        "net_worth_series": series, "advisor_note": advisor_note,
        "trade_off": _constructive("The most discipline: a higher savings rate every year, the willingness to commit bonuses rather than spend them, comfort with portfolio swings, and an income trajectory that holds up."),
    }


def _path3(plan, states, retire, surplus_blk, discretionary, simulate) -> dict:
    investable = float(surplus_blk["investable_surplus"])
    income = float(plan.freedom_score_inputs.monthly_income or 0)
    conservative = _is_conservative(plan)
    step = PATH3_STEPUP
    levers = [{"text": f"SIP step-up {_pct(SIP_STEPUP_PCT)}/yr → {_pct(step)}/yr (moderate)"}]

    # Lever 4 — half the available lumpsum pool.
    pool = _lumpsum_pool(plan, surplus_blk)
    lump = float(pool["total"]) / 2.0
    if lump > 0:
        _apply_lumpsum(states, retire, lump)
        levers.append({"text": f"Commit about half your expected/idle lumpsums (~{_compact(lump)}) to your largest goal"})

    # One small lifestyle adjustment — delay the largest flexible goal by 2 years.
    flex = [s for s in states if s["gap"] > 0 and _year_flexible(s) and s["yrs"] > 0]
    adjusted = None
    if flex:
        adjusted = max(flex, key=lambda s: s["gap"])
        _do_delay(adjusted, 2)
        levers.append({"text": f"Small adjustment: move {adjusted['name']} {adjusted['orig_year']}→{adjusted['target_year']}"})

    # Lever 7 — moderate expense optimisation.
    expense_opt = _r500(min(0.15 * discretionary, 12000)) if discretionary > 1000 else 0
    if expense_opt > 0:
        levers.append({"text": f"Find ~{_rupees(expense_opt)}/mo from discretionary spend"})

    available = investable + expense_opt
    used_equity = False
    if _required_start(states, retire, step) > available:
        used_equity = _do_equity(states, retire)
        if used_equity:
            levers.append({"text": "Higher-risk equity for goals ≥ 10 years away: Hybrid (10.5%) → Aggressive (12.25% post-tax). "
                                   + (LEVER8_CAUTION if conservative else LEVER8_DEFAULT),
                           "lever8": True})

    required = _required_start(states, retire, step)
    residual = max(0.0, required - available)
    income_nudge = round(residual)
    if income_nudge > 0:
        levers.append({"text": _constructive(
            f"A modest income lift of about {_rupees(income_nudge)}/month closes the remaining gap.")})
    available += residual
    achieved = True

    corpus = _retire_corpus(retire, required, available, step)
    retire["projected_corpus"] = corpus
    retire["target_year"] = datetime.now().year + retire["yrs"]
    series = _project_series(plan, simulate, step_up=step, deploy=investable, income_bump=income_nudge,
                             delays=[(adjusted["idx"], adjusted["target_year"])] if adjusted else [],
                             reductions=[], lumpsum_amt=lump)

    return {
        "key": "path3", "name": "Path 3 — Balanced",
        "headline": _constructive("Most of the plan runs as originally intended; a small lifestyle adjustment and a moderate lift in savings discipline carry the rest."),
        "levers": levers, "caution": (LEVER8_CAUTION if (conservative and used_equity) else None),
        "monthly_sip": round(required), "retirement_age": _retire_age(retire),
        "retirement_corpus": corpus, "corpus_required": round(retire["corpus_required"]),
        "goals_met_pct": 100, "achieved": achieved,
        "outcomes": _outcomes(states, retire, True, 100),
        "net_worth_series": series, "advisor_note": None,
        "trade_off": _constructive("A balanced mix — savings up moderately, one lifestyle goal adjusts a little, no single dial cranked all the way."),
    }


def _retire_age(retire: dict) -> int:
    return RETIREMENT_CAP_AGE  # placeholder overwritten by caller


# ── Orchestrator ────────────────────────────────────────────────────────────

def compute_scenarios(plan: PlanState, overrides: Optional[dict] = None) -> dict:
    from .scenario import simulate_mutation  # local import avoids cycle

    plan = _apply_overrides(plan, overrides)
    cfp = compute_cfp(plan)
    s = cfp.summary
    ret = cfp.retirement
    current_year = datetime.now().year

    surplus_blk = compute_investable_surplus(plan, cfp)
    investable = float(surplus_blk["investable_surplus"])
    discretionary = _discretionary_monthly(plan, cfp)

    goal_incremental = float(s.get("total_incremental_sip_monthly", 0) or 0)
    retire_required = float(ret.get("required_monthly_sip", 0) or 0)
    total_needed = goal_incremental + retire_required
    retire_age = int(ret.get("retirement_age", 60) or 60)
    corpus_required = float(ret.get("corpus_required", 0) or 0)

    verdict = _verdict(investable, total_needed, retire_age)
    top_actions = _top_actions(plan, cfp, surplus_blk, verdict["achievable"])

    baseline_series = [{"year": p.year, "value": p.value} for p in (plan.computed.net_worth_series or [])]
    existing_sip = float(s.get("monthly_existing_sip", 0) or 0)
    baseline_scenario = {
        "key": "baseline", "name": "Baseline — current trajectory",
        "headline": _constructive(verdict["text"]), "levers": [], "caution": None,
        "monthly_sip": round(existing_sip), "retirement_age": retire_age,
        "retirement_corpus": round((ret.get("stepup_plan") or {}).get("projected_corpus_at_retirement", 0) or 0),
        "corpus_required": round(corpus_required), "net_worth_series": baseline_series,
        "goals_met_pct": round(min(100.0, (investable / total_needed * 100) if total_needed else 100.0)),
        "outcomes": [], "advisor_note": None,
        "trade_off": "No changes to your life — but the fuller plan stays partly unfunded." if not verdict["achievable"] else "No changes needed; keep the current SIPs running.",
    }

    result = {
        "generated_at": datetime.now().isoformat(), "as_of_year": current_year,
        "surplus": surplus_blk, "total_sip_needed": round(total_needed),
        "goal_sip_needed": round(goal_incremental), "retirement_sip_needed": round(retire_required),
        "verdict": verdict, "top_actions": top_actions, "achievable": verdict["achievable"],
        "risk_profile": _risk_label(plan), "baseline": baseline_scenario,
    }

    if verdict["achievable"]:
        result["single_plan"] = {
            "headline": _constructive(
                f"One plan funds everything: deploy {_rupees(round(total_needed))}/mo across your goals "
                f"(you have {_rupees(round(investable))}/mo of investable surplus), step SIPs up "
                f"{round(SIP_STEPUP_PCT*100)}%/yr with income, and route the cushion to a larger retirement buffer."),
            "monthly_sip": round(total_needed),
            "cushion_monthly": round(max(0.0, investable - total_needed)),
            "step_up_pct": SIP_STEPUP_PCT,
        }
        result["scenarios"] = [baseline_scenario]
        result["which_path"] = []
        return result

    # ── §6.5 — three paths, each its own independent state set ────────────────
    paths = []
    for builder in (_path1, _path2, _path3):
        states = _goal_states(plan, cfp)
        retire_st = _retire_state(ret)
        path = builder(plan, states, retire_st, surplus_blk, discretionary, simulate_mutation)
        path["retirement_age"] = retire_age  # overwrite placeholder
        for o in path.get("outcomes", []):
            if o.get("goal") == "Retirement":
                o["target_year"] = current_year + retire_st["yrs"]
        paths.append(path)

    result["scenarios"] = [baseline_scenario, *paths]
    result["comparison"] = _comparison(baseline_scenario, paths)
    result["which_path"] = [
        {"path": "Path 1 — Reducing Expectations", "suits": "The least disruption to current life. Your essential goals and retirement stay fully on track while a couple of lifestyle goals move out and scale down. No demand on your savings rate or income."},
        {"path": "Path 2 — Stretching Ourselves", "suits": "Every goal at its original year and amount. It asks the most: a higher savings rate, committing your bonuses, comfort with market swings, and an income trajectory that holds up."},
        {"path": "Path 3 — Balanced", "suits": "The middle path. Savings up moderately, one lifestyle goal adjusts a little, no single dial cranked all the way — a balanced demand in every direction."},
    ]
    return result


def _comparison(baseline: dict, paths: list[dict]) -> list[dict]:
    p1, p2, p3 = paths[0], paths[1], paths[2]
    rows = [("Monthly SIP", "monthly_sip", "money"), ("Goals funded", "goals_met_pct", "pct"),
            ("Retirement age", "retirement_age", "age"), ("Retirement corpus", "retirement_corpus", "money")]
    out = []
    for label, k, kind in rows:
        out.append({"metric": label, "kind": kind, "baseline": baseline.get(k),
                    "path1": p1.get(k), "path2": p2.get(k), "path3": p3.get(k)})
    out.append({"metric": "Biggest trade-off", "kind": "text", "baseline": baseline.get("trade_off"),
                "path1": p1.get("trade_off"), "path2": p2.get("trade_off"), "path3": p3.get("trade_off")})
    return out


def _top_actions(plan, cfp, surplus_blk, achievable) -> list[str]:
    actions: list[str] = []
    ins = cfp.insurance or {}
    add_term = ins.get("additional_cover_required", 0) or 0
    if add_term > 0:
        actions.append(_constructive(f"Add about {_compact(add_term)} of term life cover — it protects the whole plan if anything happens to the earner."))
    ef = surplus_blk
    if ef["emergency_current"] < ef["emergency_target"]:
        actions.append(_constructive(f"Build your emergency fund to {_compact(ef['emergency_target'])} ({_rupees(ef['emergency_build_sip'])}/mo into a liquid fund) before ramping other SIPs."))
    if not achievable:
        actions.append("Pick a path below — each one funds 100% of your goals a different way (Path 1 reshapes, Path 2 stretches, Path 3 balances).")
    else:
        actions.append(_constructive(f"Step up your SIPs {round(SIP_STEPUP_PCT*100)}%/yr with each salary increment to widen the retirement cushion."))
    if len(actions) < 3:
        actions.append("Review the plan every April — step up SIPs, rebalance, and re-run as income and goals change.")
    return actions[:3]
