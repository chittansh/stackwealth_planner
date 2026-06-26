"""
Post-extraction input validation — the layer between intake and the
calculations.

After the intake pipeline writes a PlanState, the calculation skills (risk,
freedom, cfp, cashflow, retirement corpus, Monte Carlo, tax, debt) and the
firm's Excel engine all read from it. None of them hard-fail on missing data —
they default, clamp, or silently produce a meaningless projection. This module
is the sanity gate that runs BEFORE the RM trusts those numbers. It answers
three questions:

  1. COMPLETENESS — are the inputs every calculation needs actually present?
     (`_check_required_inputs`) — missing income, age/DOB, retirement age, etc.

  2. VALUE SANITY — does any extracted value look hardcoded, double-counted,
     out-of-range, or like a placeholder/sample leak? (`_check_suspect_values`)
     The canonical case this catches: a fixed-income maturity (NSC/FD/PPF…)
     re-injected as a lumpsum cash inflow, double-counting money the FA opening
     balance already holds and compounds.

  3. CONTRADICTIONS — the existing post-upload anomaly scan
     (`skills.anomalies.detect_plan_anomalies`) is folded in here so there's
     ONE validation entry point.

Everything is ADVISORY: findings carry an RM-facing `question`. The chat agent
reads them (via the `validate_inputs` tool or the upload context) and asks the
RM rather than narrating a confident-but-wrong plan. Calculations still run.

Finding shape (same as anomalies, plus `kind`):
    kind       : "required_missing" | "suspect_value" | "anomaly"
    severity   : "high" | "medium" | "low"
    category   : completeness | double_count | range | placeholder | sample |
                 + the anomaly categories (surplus/income/retirement/…)
    field      : dotted PlanState path the finding is about
    value      : the triggering value (for context)
    message    : human-readable description (logs / debug)
    question   : the EXACT question the agent should ask the RM in chat
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..types import PlanState
from .anomalies import detect_plan_anomalies

# Instrument keywords that mean "this is an existing fixed-income holding".
# A lumpsum event whose label mentions one of these is almost certainly a
# maturity already inside the FA portfolio (it compounds there) — re-adding it
# as a cash inflow double-counts. See intake.py's own rule forbidding this.
_FI_MATURITY_KEYWORDS = (
    "nsc", "ppf", "epf", "nps", "bond", "debenture", "post office",
    "fixed deposit", "fd ", " fd", "fd/", "/fd", "recurring deposit",
    "maturity", "matures", "maturing", "maturity proceeds",
)

# Strings that only appear in the firm's SAMPLE workbook — if they survive into
# a real client's plan, intake leaked sample data instead of clearing it.
_SAMPLE_SENTINELS = (
    "knee surgery", "balance sale consideration", "sandeep", "naman modi",
    "vignesh",
)


def _current_year() -> int:
    return datetime.now().year


def _age_from_dob(dob: Optional[str]) -> Optional[int]:
    """Best-effort age from a DOB string in DD-MM-YYYY or YYYY-MM-DD form."""
    if not dob:
        return None
    parts = str(dob).replace("/", "-").split("-")
    years = [int(x) for x in parts if x.isdigit() and len(x) == 4 and 1900 < int(x) < 2100]
    if not years:
        return None
    return _current_year() - years[0]


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _person0(plan: PlanState):
    persons = (plan.assumptions.persons or []) if plan.assumptions else []
    return persons[0] if persons else None


# ── 1. Completeness — required inputs per calculation ──────────────────────


def _check_required_inputs(plan: PlanState) -> list[dict[str, Any]]:
    """Flag inputs the calculations need but that are absent or zero. Each
    missing field is reported once, listing which calculations it blocks."""
    out: list[dict[str, Any]] = []
    fsi = plan.freedom_score_inputs
    pd = plan.personal_details
    p0 = _person0(plan)
    rpi = plan.retirement_plan_inputs

    income = _num(fsi.monthly_income) if fsi else None
    expenses = _num(fsi.monthly_expenses) if fsi else None
    portfolio = _num(fsi.portfolio_current_value) if fsi else None
    liquid = _num(fsi.liquid_assets_current_value) if fsi else None
    age = _num(fsi.age) if fsi else None
    dob = (pd.date_of_birth if pd else None) or (p0.date_of_birth if p0 else None)
    derived_age = age or _age_from_dob(dob)

    def add(severity, field, value, message, question, calcs):
        out.append({
            "kind": "required_missing",
            "severity": severity,
            "category": "completeness",
            "field": field,
            "value": value,
            "message": message,
            "blocks": calcs,
            "question": question,
        })

    if income is None or income <= 0:
        add("high", "freedom_score_inputs.monthly_income", income,
            "Monthly income missing or zero — every cash-flow calc keys off it.",
            "I don't have a monthly income figure. What's the household's take-home "
            "income per month (salary + business + rental, after tax)?",
            ["risk", "freedom_score", "cfp", "cashflow", "montecarlo", "debt"])

    if expenses is None or expenses <= 0:
        add("high", "freedom_score_inputs.monthly_expenses", expenses,
            "Monthly expenses missing or zero.",
            "I don't have monthly household expenses. Roughly what are the total "
            "monthly outgoings (living costs, not EMIs)?",
            ["risk", "freedom_score", "cfp", "cashflow", "montecarlo"])

    if portfolio is None:
        add("high", "freedom_score_inputs.portfolio_current_value", None,
            "Investable portfolio value not captured.",
            "What's the current total value of the investment portfolio "
            "(mutual funds + equity + other market investments)?",
            ["freedom_score", "cfp", "cashflow", "montecarlo"])

    if liquid is None:
        add("medium", "freedom_score_inputs.liquid_assets_current_value", None,
            "Liquid-assets value not captured (falls back to liquid_capital).",
            "How much is held in liquid/near-cash assets (savings, idle cash, "
            "breakable FDs)? Needed for the emergency-fund and risk-capacity math.",
            ["risk", "freedom_score", "cfp", "cashflow", "montecarlo"])

    if derived_age is None:
        add("high", "freedom_score_inputs.age", None,
            "No age and no parseable date of birth — horizon math can't anchor.",
            "I can't determine the client's current age (no DOB on file). What's "
            "the client's date of birth (or current age)?",
            ["freedom_score", "cfp", "cashflow", "montecarlo", "retirement"])

    if not dob:
        add("high", "personal_details.date_of_birth", None,
            "Date of birth missing — Excel engine and retirement glide need it.",
            "What's the client's date of birth? The retirement glide-path and the "
            "firm's Excel model both compute from it.",
            ["cfp", "excel", "retirement"])

    retire_age = (pd.retirement_age_target if pd else None) or (p0.retirement_age if p0 else None)
    if retire_age is None:
        add("high", "personal_details.retirement_age_target", None,
            "Retirement age missing — corpus and cash-flow horizon undefined.",
            "At what age does the client plan to retire? Without it the retirement "
            "corpus and the post-retirement drawdown can't be sized.",
            ["cfp", "cashflow", "montecarlo", "retirement"])

    life_exp = (p0.life_expectancy if p0 else None) or (rpi.self_life_expectancy if rpi else None)
    if life_exp is None:
        add("medium", "assumptions.persons[0].life_expectancy", None,
            "Life expectancy missing — corpus calc defaults to 85.",
            "What life expectancy should I plan to? (It sets how many retirement "
            "years the corpus must fund — I'll assume 85 if you're unsure.)",
            ["cfp", "retirement", "montecarlo"])

    if not (plan.financial_goals or []):
        add("medium", "financial_goals", [],
            "No financial goals captured — goal-funding calcs have nothing to size.",
            "I don't see any financial goals (children's education, home, car, "
            "etc.). Are there goals to plan for, or is this retirement-only?",
            ["cfp", "cashflow", "montecarlo"])

    return out


# ── 2. Value sanity — hardcoding / double-count / range / placeholder ──────


def _check_suspect_values(plan: PlanState) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    yr = _current_year()

    def add(severity, category, field, value, message, question):
        out.append({
            "kind": "suspect_value",
            "severity": severity,
            "category": category,
            "field": field,
            "value": value,
            "message": message,
            "question": question,
        })

    asn = plan.assumptions

    # 2a. Fixed-income maturity re-injected as a lumpsum (double-count). This is
    # the canonical bug — a holding already in the FA portfolio added again as a
    # cash inflow. A NEGATIVE amount is a withdrawal/spend, which is legitimate.
    for ev in (asn.lumpsum_events or []) if asn else []:
        label = (ev.label or "").lower()
        amt = _num(ev.amount)
        if amt is not None and amt > 0 and any(k in label for k in _FI_MATURITY_KEYWORDS):
            add("high", "double_count", f"assumptions.lumpsum_events[{ev.year}]",
                {"year": ev.year, "amount": ev.amount, "label": ev.label},
                f"Lumpsum inflow of ₹{int(amt):,} in {ev.year} is labelled like a "
                f"fixed-income maturity ('{ev.label}') — those holdings already sit "
                f"in the portfolio and compound there, so this likely double-counts.",
                f"The plan adds a ₹{int(amt):,} inflow in {ev.year} labelled "
                f"'{ev.label}'. If that's just an existing FD/NSC/PPF maturing, it's "
                f"already inside the portfolio and shouldn't be added again. Is this a "
                f"NEW external inflow (sale/bonus/inheritance), or an existing holding "
                f"maturing? If the latter, I'll remove it to avoid double-counting.")

        # 2b. Lumpsum year out of plausible range.
        if ev.year and (ev.year < yr or ev.year > yr + 80):
            add("medium", "range", f"assumptions.lumpsum_events[{ev.year}]",
                ev.year,
                f"Lumpsum event year {ev.year} is in the past or implausibly far out.",
                f"There's a one-off cash event dated {ev.year} (₹{int(amt or 0):,}, "
                f"'{ev.label}'). That year looks off — is it correct?")

        # 2c. Sample-sentinel leak in the label.
        if any(s in (ev.label or "").lower() for s in _SAMPLE_SENTINELS):
            add("medium", "sample", f"assumptions.lumpsum_events[{ev.year}]",
                ev.label,
                f"Lumpsum label '{ev.label}' matches firm-sample data — possible leak.",
                f"There's an event labelled '{ev.label}' — that looks like it came "
                f"from the firm's sample template, not this client. Should I remove it?")

    # 2d. Rate stored as a percent (7) instead of a fraction (0.07).
    if asn:
        rate_checks = [("assumptions.inflation", _num(asn.inflation))]
        g = asn.growth
        if g is not None:
            for name in ("investment", "cash", "real_estate"):
                rate_checks.append((f"assumptions.growth.{name}", _num(getattr(g, name, None))))
        for field, rv in rate_checks:
            if rv is not None and rv > 1.0:
                add("medium", "range", field, rv,
                    f"{field} = {rv} looks like a percentage, not a fraction "
                    f"(expected ~0.0–0.20).",
                    f"The assumption {field.split('.')[-1]} is set to {rv} — that reads "
                    f"like {rv}% entered as a whole number. Should it be {rv/100:.4f}?")

    # 2e. Calendar-year-as-age and impossible ages.
    age_fields = []
    pd = plan.personal_details
    fsi = plan.freedom_score_inputs
    if fsi and fsi.age is not None:
        age_fields.append(("freedom_score_inputs.age", fsi.age))
    if pd and pd.retirement_age_target is not None:
        age_fields.append(("personal_details.retirement_age_target", pd.retirement_age_target))
    for p in (asn.persons or []) if asn else []:
        if p.retirement_age is not None:
            age_fields.append((f"assumptions.persons[{p.name}].retirement_age", p.retirement_age))
        if p.life_expectancy is not None:
            age_fields.append((f"assumptions.persons[{p.name}].life_expectancy", p.life_expectancy))
    for field, v in age_fields:
        nv = _num(v)
        if nv is not None and nv > 120:
            add("high", "range", field, v,
                f"{field} = {v} exceeds any human age — looks like a calendar year.",
                f"{field.split('.')[-1].replace('_', ' ')} is {v}, which can't be an "
                f"age — it looks like a calendar year got entered. What's the correct age?")

    # 2f. Negative where only positive makes sense.
    neg_checks = []
    if fsi:
        neg_checks = [
            ("freedom_score_inputs.monthly_income", _num(fsi.monthly_income)),
            ("freedom_score_inputs.monthly_expenses", _num(fsi.monthly_expenses)),
            ("freedom_score_inputs.portfolio_current_value", _num(fsi.portfolio_current_value)),
            ("freedom_score_inputs.liquid_assets_current_value", _num(fsi.liquid_assets_current_value)),
        ]
    for field, v in neg_checks:
        if v is not None and v < 0:
            add("high", "range", field, v,
                f"{field} is negative ({v}).",
                f"{field.split('.')[-1].replace('_', ' ')} came through as a negative "
                f"number ({int(v):,}). Is that a sign error?")

    # 2g. Goal target year in the past.
    for goal in plan.financial_goals or []:
        if goal.target_year and goal.target_year < yr:
            add("medium", "range", f"financial_goals[{goal.goal_name}].target_year",
                goal.target_year,
                f"Goal '{goal.goal_name}' targets {goal.target_year}, already past.",
                f"The goal '{goal.goal_name}' is dated {goal.target_year}, which is in "
                f"the past. Has it already happened, or is the year wrong?")
        if any(s in (goal.goal_name or "").lower() for s in _SAMPLE_SENTINELS):
            add("medium", "sample", f"financial_goals[{goal.goal_name}].goal_name",
                goal.goal_name,
                f"Goal name '{goal.goal_name}' matches firm-sample data — possible leak.",
                f"There's a goal named '{goal.goal_name}' that looks like sample data, "
                f"not this client's. Should I remove it?")

    # 2h. Placeholder heuristic — the same round value repeated across several
    # unrelated money fields often means a default was typed everywhere.
    round_vals: dict[float, set[str]] = {}
    money_fields: list[tuple[str, Any]] = []
    if fsi:
        money_fields += [
            ("freedom_score_inputs.monthly_income", fsi.monthly_income),
            ("freedom_score_inputs.monthly_expenses", fsi.monthly_expenses),
            ("freedom_score_inputs.portfolio_current_value", fsi.portfolio_current_value),
            ("freedom_score_inputs.liquid_assets_current_value", fsi.liquid_assets_current_value),
        ]
    for goal in plan.financial_goals or []:
        money_fields.append((f"financial_goals[{goal.goal_name}].target_amount", goal.target_amount))
    for field, v in money_fields:
        nv = _num(v)
        if nv is not None and nv >= 100_000 and nv % 50_000 == 0:
            round_vals.setdefault(nv, set()).add(field)
    for val, fields in round_vals.items():
        if len(fields) >= 4:
            add("low", "placeholder", "multiple",
                {"value": val, "fields": sorted(fields)},
                f"The round value ₹{int(val):,} appears in {len(fields)} unrelated "
                f"fields — may be a placeholder rather than real data.",
                f"The same round figure ₹{int(val):,} shows up across "
                f"{len(fields)} different fields — that sometimes means a default was "
                f"entered everywhere. Can you confirm these are the real numbers?")

    return out


# ── Public entry point ─────────────────────────────────────────────────────


def validate_plan(plan: PlanState) -> dict[str, Any]:
    """Run the full post-extraction validation. Returns a structured report the
    `validate_inputs` tool persists and the chat agent reads to ask the RM.

    `ok` is True when nothing high-severity surfaced — i.e. the plan is safe to
    narrate without a clarifying question first."""
    required = _check_required_inputs(plan)
    suspect = _check_suspect_values(plan)
    anomalies = [{**a, "kind": "anomaly"} for a in detect_plan_anomalies(plan)]

    findings = required + suspect + anomalies
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order.get(f.get("severity", "low"), 2))

    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f.get("severity", "low")] = counts.get(f.get("severity", "low"), 0) + 1
    counts["total"] = len(findings)

    return {
        "ok": counts["high"] == 0,
        "counts": counts,
        "findings": findings,
        "required_missing": required,
        "suspect_values": suspect,
        "anomalies": anomalies,
    }


def format_validation_for_agent(report: dict[str, Any]) -> str:
    """Render a validation report into a block the chat agent reads and turns
    into numbered questions. Sorted high → medium → low."""
    findings = report.get("findings") or []
    if not findings:
        return ""
    lines = [
        "",
        "VALIDATION FINDINGS — ASK THE RM BEFORE NARRATING THE PLAN AS CORRECT:",
    ]
    for i, f in enumerate(findings, 1):
        sev = str(f.get("severity", "?")).upper()
        kind = f.get("kind", "?")
        cat = f.get("category", "?")
        lines.append(f"  {i}. [{sev}/{kind}/{cat}] {f.get('message', '')}")
        lines.append(f"     → ASK: {f.get('question', '')}")
    return "\n".join(lines)
