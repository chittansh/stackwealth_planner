"""
Risk profile — port of skills/risk/index.ts.
3-part Capacity / Need / Willingness, reconciled.
"""
from __future__ import annotations

from typing import Any

from ..db import get_plan
from ..tracing import traced_calc
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


@traced_calc("calc.risk")
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


# ─────────────────────────────────────────────────────────────────────────
# 17-question Risk Questionnaire — Excel `Risk Questannaire` tab
#
# Each Q has options scored 1–5. Total bucketed:
#   17–34 → Conservative
#   35–50 → Moderately Conservative
#   51–67 → Moderate
#   68–76 → Moderately Aggressive
#   77–85 → Aggressive
# ─────────────────────────────────────────────────────────────────────────

RISK_QUESTIONNAIRE = [
    # ── Section A: Investment knowledge ─────────────────────────────────
    {"id": "Q1", "section": "knowledge",
     "text": "How would you rate your investment knowledge?",
     "options": [
         {"label": "Beginner",       "score": 1},
         {"label": "Some experience","score": 2},
         {"label": "Average",        "score": 3},
         {"label": "Above average",  "score": 4},
         {"label": "Expert",         "score": 5}]},
    {"id": "Q2", "section": "knowledge",
     "text": "Which of these have you previously invested in?",
     "options": [
         {"label": "Only bank deposits",                     "score": 1},
         {"label": "Bank deposits + insurance plans",        "score": 2},
         {"label": "Mutual funds",                           "score": 3},
         {"label": "Direct stocks",                          "score": 4},
         {"label": "Derivatives / alternates / international","score": 5}]},
    {"id": "Q3", "section": "knowledge",
     "text": "How do you usually make investment decisions?",
     "options": [
         {"label": "I rely entirely on someone else",  "score": 1},
         {"label": "Family / friend recommendation",   "score": 2},
         {"label": "Advisor + my own check",           "score": 3},
         {"label": "Mostly my own research",           "score": 4},
         {"label": "Entirely self-directed",           "score": 5}]},

    # ── Section B: Time horizon & life stage ────────────────────────────
    {"id": "Q4", "section": "horizon",
     "text": "What is your investment time horizon?",
     "options": [
         {"label": "Less than 1 year",  "score": 1},
         {"label": "1–3 years",         "score": 2},
         {"label": "3–5 years",         "score": 3},
         {"label": "5–10 years",        "score": 4},
         {"label": "More than 10 years","score": 5}]},
    {"id": "Q5", "section": "horizon",
     "text": "When do you expect to start drawing on these investments?",
     "options": [
         {"label": "Within 1 year",                        "score": 1},
         {"label": "1–3 years",                            "score": 2},
         {"label": "3–7 years",                            "score": 3},
         {"label": "7–15 years",                           "score": 4},
         {"label": "Only after retirement / never planned","score": 5}]},
    {"id": "Q6", "section": "horizon",
     "text": "Your current age bracket?",
     "options": [
         {"label": "55+",      "score": 1},
         {"label": "45–55",    "score": 2},
         {"label": "35–45",    "score": 3},
         {"label": "25–35",    "score": 4},
         {"label": "Under 25", "score": 5}]},

    # ── Section C: Financial position ───────────────────────────────────
    {"id": "Q7", "section": "position",
     "text": "Stability of your primary income source?",
     "options": [
         {"label": "Highly volatile / contract",         "score": 1},
         {"label": "Business / freelance",               "score": 2},
         {"label": "Private salaried, mid stability",    "score": 3},
         {"label": "Salaried, stable",                   "score": 4},
         {"label": "Government / very secure",           "score": 5}]},
    {"id": "Q8", "section": "position",
     "text": "How many months of expenses do your emergency reserves cover?",
     "options": [
         {"label": "< 1 month",      "score": 1},
         {"label": "1–3 months",     "score": 2},
         {"label": "3–6 months",     "score": 3},
         {"label": "6–12 months",    "score": 4},
         {"label": "More than 12 months","score": 5}]},
    {"id": "Q9", "section": "position",
     "text": "Number of dependents you financially support?",
     "options": [
         {"label": "More than 4", "score": 1},
         {"label": "3–4",         "score": 2},
         {"label": "2",           "score": 3},
         {"label": "1",           "score": 4},
         {"label": "None",        "score": 5}]},
    {"id": "Q10", "section": "position",
     "text": "What share of your annual income do you save/invest?",
     "options": [
         {"label": "< 5%",       "score": 1},
         {"label": "5–10%",      "score": 2},
         {"label": "10–20%",     "score": 3},
         {"label": "20–35%",     "score": 4},
         {"label": "More than 35%","score": 5}]},
    {"id": "Q11", "section": "position",
     "text": "What % of net worth is in liquid investable assets (excluding home / vehicle)?",
     "options": [
         {"label": "< 10%",      "score": 1},
         {"label": "10–25%",     "score": 2},
         {"label": "25–50%",     "score": 3},
         {"label": "50–75%",     "score": 4},
         {"label": "More than 75%","score": 5}]},

    # ── Section D: Willingness to take risk ─────────────────────────────
    {"id": "Q12", "section": "willingness",
     "text": "Which statement best describes your investment goal?",
     "options": [
         {"label": "Protect capital, beat inflation slightly", "score": 1},
         {"label": "Steady income with some growth",           "score": 2},
         {"label": "Balanced growth + income",                 "score": 3},
         {"label": "Mostly long-term growth",                  "score": 4},
         {"label": "Maximise long-term growth, accept big swings","score": 5}]},
    {"id": "Q13", "section": "willingness",
     "text": "Pick the portfolio you would be most comfortable owning over 10 years:",
     "options": [
         {"label": "Avg 5% return / worst-year -2%",   "score": 1},
         {"label": "Avg 7% return / worst-year -8%",   "score": 2},
         {"label": "Avg 9% return / worst-year -15%",  "score": 3},
         {"label": "Avg 11% return / worst-year -25%", "score": 4},
         {"label": "Avg 13% return / worst-year -35%", "score": 5}]},
    {"id": "Q14", "section": "willingness",
     "text": "If you had a windfall of ₹10 lakh, where would you put most of it?",
     "options": [
         {"label": "Bank FD / liquid funds",      "score": 1},
         {"label": "Debt mutual funds / bonds",   "score": 2},
         {"label": "Hybrid funds",                "score": 3},
         {"label": "Equity mutual funds",         "score": 4},
         {"label": "Direct stocks / alternates",  "score": 5}]},

    # ── Section E: Risk perception & past reaction ──────────────────────
    {"id": "Q15", "section": "perception",
     "text": "If your portfolio fell 20% in one year, what would you do?",
     "options": [
         {"label": "Sell everything",                       "score": 1},
         {"label": "Move part to safer assets",             "score": 2},
         {"label": "Hold and wait",                         "score": 3},
         {"label": "Hold and continue SIPs",                "score": 4},
         {"label": "Invest more to average down",           "score": 5}]},
    {"id": "Q16", "section": "perception",
     "text": "How often do you check your portfolio?",
     "options": [
         {"label": "Daily — every move worries me",     "score": 1},
         {"label": "Weekly",                            "score": 2},
         {"label": "Monthly",                           "score": 3},
         {"label": "Quarterly",                         "score": 4},
         {"label": "Half-yearly or less",               "score": 5}]},
    {"id": "Q17", "section": "perception",
     "text": "Which of these have you personally lived through with your money invested?",
     "options": [
         {"label": "Never invested through a downturn",        "score": 1},
         {"label": "I exited when markets fell",               "score": 2},
         {"label": "I held, mostly nervous",                   "score": 3},
         {"label": "I held calmly and recovered",              "score": 4},
         {"label": "I invested more during the downturn",      "score": 5}]},
]


def _bucket_from_questionnaire_total(total: int) -> str:
    if total <= 34:
        return "Conservative"
    if total <= 50:
        return "Moderately Conservative"
    if total <= 67:
        return "Moderate"
    if total <= 76:
        return "Moderately Aggressive"
    return "Aggressive"


def compute_questionnaire_score(answers: dict[str, int]) -> dict:
    """Score the 17-question instrument from Excel `Risk Questannaire`.

    `answers` is a dict of {question_id → score} where score is the value
    (1–5) of the option the user picked.

    Returns total score, section breakdown, recommended profile, and a
    list of any questions still missing (so the UI can prompt for them).
    """
    section_scores: dict[str, int] = {}
    section_counts: dict[str, int] = {}
    answered = 0
    missing: list[str] = []
    for q in RISK_QUESTIONNAIRE:
        qid = q["id"]
        sec = q["section"]
        if qid in answers and isinstance(answers[qid], (int, float)):
            score = int(answers[qid])
            section_scores[sec] = section_scores.get(sec, 0) + score
            section_counts[sec] = section_counts.get(sec, 0) + 1
            answered += 1
        else:
            missing.append(qid)
    total = sum(section_scores.values())
    profile = _bucket_from_questionnaire_total(total) if not missing else None
    # Normalised 0–100 score so it composes with capacity / willingness / need.
    max_total = len(RISK_QUESTIONNAIRE) * 5  # 85
    min_total = len(RISK_QUESTIONNAIRE) * 1  # 17
    normalised = round(((total - min_total) / (max_total - min_total)) * 100, 1) if total else 0
    return {
        "answered": answered,
        "total_questions": len(RISK_QUESTIONNAIRE),
        "missing_question_ids": missing,
        "section_scores": section_scores,
        "section_question_counts": section_counts,
        "total_score": total,
        "normalised_score_0_100": normalised,
        "recommended_profile": profile,
        "is_complete": len(missing) == 0,
    }


async def questionnaire(args: dict[str, Any]) -> dict:
    """Tool entry point — score a partial or complete questionnaire."""
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    answers = args.get("answers") or {}
    return {
        "questionnaire": RISK_QUESTIONNAIRE,
        "result": compute_questionnaire_score(answers),
    }
