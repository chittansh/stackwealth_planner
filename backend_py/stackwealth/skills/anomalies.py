"""
Plan anomaly detection — post-upload sanity checks.

After extraction completes, this scans the saved PlanState for values
that look wrong, contradictory, or planning-impossible. Findings are
returned as structured items so the chat agent can ASK the RM about
them in conversation, rather than the engine silently producing a
nonsensical projection (retirement at age 2030, negative surplus
treated as if affordable, life expectancy below retirement age, etc.).

Each finding has:
    severity   : "high"   — likely data-entry error; ASK before proceeding
                 "medium" — possible but worth confirming
                 "low"    — informational
    category   : surplus | income | expense | retirement | insurance |
                 emergency | data
    field      : dotted PlanState path the anomaly is about
    value      : the value that triggered it (for context)
    message    : human-readable description (for logs / debug)
    question   : the EXACT question the agent should ask the RM in chat

The agent's chat prompt is wired to:
  - read `upload_context.anomalies` before narrating
  - if any are present, ASK the questions in priority (high → medium →
    low) instead of pretending the plan is fine
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..types import PlanState


def detect_plan_anomalies(plan: PlanState) -> list[dict[str, Any]]:
    """Return a list of anomaly findings the chat agent should surface
    to the RM. Empty list = plan looks consistent enough to proceed."""
    findings: list[dict[str, Any]] = []

    fsi = plan.freedom_score_inputs
    monthly_income = fsi.monthly_income or 0
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0

    mi = plan.monthly_investments
    existing_sip = 0.0
    if mi:
        existing_sip = float(
            (mi.mutual_fund_sip or 0) + (mi.nps or 0) + (mi.ppf or 0)
            + (mi.rd or 0) + (mi.direct_equity or 0)
        )

    pre_sip_surplus = monthly_income - monthly_expenses - monthly_emi
    post_sip_surplus = pre_sip_surplus - existing_sip

    # ── 1. Income looks too low / missing entirely ────────────────────
    if monthly_income == 0 and (monthly_expenses > 0 or existing_sip > 0):
        findings.append({
            "severity": "high",
            "category": "income",
            "field": "freedom_score_inputs.monthly_income",
            "value": 0,
            "message": "Expenses or SIPs are populated but monthly_income is zero.",
            "question": (
                "I see expenses and/or existing SIPs in the file but no monthly income. "
                "Is there a salary, business income, or rental I'm missing? Please share."
            ),
        })

    # ── 2. Expenses zero but plausibly should have some ───────────────
    if monthly_income > 0 and monthly_expenses == 0:
        findings.append({
            "severity": "medium",
            "category": "expense",
            "field": "freedom_score_inputs.monthly_expenses",
            "value": 0,
            "message": "Income populated but monthly_expenses is zero.",
            "question": (
                "Monthly expenses appear to be zero in the file — that's unusual. "
                "Could you confirm rough monthly outgoings (rent, groceries, utilities)?"
            ),
        })

    # ── 3. Pre-SIP surplus negative (expenses + EMI > income) ─────────
    if monthly_income > 0 and pre_sip_surplus < 0:
        findings.append({
            "severity": "high",
            "category": "surplus",
            "field": "computed.cfp.summary.monthly_surplus_pre_sip",
            "value": round(pre_sip_surplus),
            "message": (
                f"Pre-SIP surplus is negative: income ₹{int(monthly_income):,} − "
                f"expenses ₹{int(monthly_expenses):,} − EMI ₹{int(monthly_emi):,} "
                f"= ₹{int(pre_sip_surplus):,}/mo."
            ),
            "question": (
                f"Income ₹{int(monthly_income):,}/mo is less than expenses + EMI "
                f"(₹{int(monthly_expenses + monthly_emi):,}/mo) — the household is "
                f"running a monthly deficit of ₹{int(-pre_sip_surplus):,}. Is there "
                f"additional income I'm missing (bonus, rental, business, spouse), "
                f"or are some of these expenses one-time and not recurring?"
            ),
        })

    # ── 4. Post-SIP surplus negative (existing SIPs eat surplus) ──────
    elif existing_sip > 0 and post_sip_surplus < 0:
        findings.append({
            "severity": "high",
            "category": "surplus",
            "field": "computed.cfp.summary.monthly_surplus_after_existing_sip",
            "value": round(post_sip_surplus),
            "message": (
                f"Existing SIPs (₹{int(existing_sip):,}/mo) exceed pre-SIP surplus "
                f"(₹{int(pre_sip_surplus):,}/mo) by ₹{int(-post_sip_surplus):,}/mo."
            ),
            "question": (
                f"Existing SIPs total ₹{int(existing_sip):,}/mo, which is more than "
                f"the household's surplus of ₹{int(pre_sip_surplus):,}/mo after "
                f"expenses. Either some of those SIPs are funded from savings (not "
                f"current income), or one of these is true: (a) there's extra income "
                f"not captured, (b) some SIPs are planned to be redirected for new "
                f"goals, or (c) the SIP amounts in the file are aspirational, not "
                f"actually running. Which is it?"
            ),
        })

    # ── 5. Retirement age out of plausible range ──────────────────────
    persons = plan.assumptions.persons or []
    for p in persons:
        if p.retirement_age is None:
            continue
        if p.retirement_age > 100:
            findings.append({
                "severity": "high",
                "category": "retirement",
                "field": f"assumptions.persons[{p.name}].retirement_age",
                "value": p.retirement_age,
                "message": (
                    f"{p.name}'s retirement_age is {p.retirement_age} — looks like a "
                    f"calendar year got stored as an age."
                ),
                "question": (
                    f"The file shows retirement age {p.retirement_age} for {p.name} — "
                    f"that looks like a calendar year, not an age. Should I read it "
                    f"as the retirement YEAR and compute the age from DOB instead?"
                ),
            })
        elif p.retirement_age < 50 and p.retirement_age > 0:
            # Compute current age if DOB available
            current_age = None
            if p.date_of_birth:
                try:
                    yr = int(p.date_of_birth.split("-")[-1])
                    current_age = datetime.now().year - yr
                except (ValueError, IndexError):
                    pass
            if current_age is not None:
                yrs_to_retire = p.retirement_age - current_age
                post_retire_years = (p.life_expectancy or 85) - p.retirement_age
            else:
                yrs_to_retire = None
                post_retire_years = (p.life_expectancy or 85) - p.retirement_age
            findings.append({
                "severity": "medium",
                "category": "retirement",
                "field": f"assumptions.persons[{p.name}].retirement_age",
                "value": p.retirement_age,
                "message": (
                    f"{p.name}'s retirement_age is {p.retirement_age} — unusually "
                    f"early. Years post-retirement: {post_retire_years}."
                ),
                "question": (
                    f"The file shows {p.name} retiring at age {p.retirement_age}"
                    + (f" ({yrs_to_retire} years from now)" if yrs_to_retire is not None else "")
                    + f", which means {post_retire_years} years of retirement to fund. "
                    f"That's an unusually early target — is this a FIRE-style early "
                    f"retirement plan, or should retirement age actually be later (say 58-62)?"
                ),
            })
        # Life expectancy below retirement age — impossible plan
        if p.life_expectancy and p.life_expectancy <= p.retirement_age:
            findings.append({
                "severity": "high",
                "category": "retirement",
                "field": f"assumptions.persons[{p.name}].life_expectancy",
                "value": p.life_expectancy,
                "message": (
                    f"{p.name}'s life_expectancy ({p.life_expectancy}) is at or below "
                    f"retirement_age ({p.retirement_age})."
                ),
                "question": (
                    f"Life expectancy ({p.life_expectancy}) is at or below "
                    f"retirement age ({p.retirement_age}) for {p.name} — that "
                    f"leaves zero retirement years to plan for. Should life "
                    f"expectancy be higher (typically 80–90)?"
                ),
            })

    # ── 6. Emergency fund coverage thin ───────────────────────────────
    ef = plan.emergency_fund
    if ef and ef.months_of_cover_available is not None:
        if ef.months_of_cover_available < 3 and monthly_expenses > 0:
            findings.append({
                "severity": "medium",
                "category": "emergency",
                "field": "emergency_fund.months_of_cover_available",
                "value": ef.months_of_cover_available,
                "message": (
                    f"Emergency fund covers only {ef.months_of_cover_available:.1f} "
                    f"months — recommended is 6."
                ),
                "question": (
                    f"Emergency fund only covers "
                    f"{ef.months_of_cover_available:.1f} months of expenses "
                    f"(recommended 6). Is there a plan to build it up before "
                    f"starting new SIPs, or are there other liquid assets that "
                    f"serve as the safety net?"
                ),
            })

    # ── 7. Life insurance under-cover ─────────────────────────────────
    insurance = plan.insurance_details
    if insurance and insurance.term_plan and monthly_income > 0:
        term_cover = insurance.term_plan.cover_amount or 0
        annual_income = monthly_income * 12
        # Rule of thumb: at least 10× annual income
        if term_cover > 0 and term_cover < 10 * annual_income:
            findings.append({
                "severity": "low",
                "category": "insurance",
                "field": "insurance_details.term_plan.cover_amount",
                "value": term_cover,
                "message": (
                    f"Term-plan cover ₹{int(term_cover):,} is less than 10× annual "
                    f"income (₹{int(10 * annual_income):,})."
                ),
                "question": (
                    f"Existing term-life cover is ₹{term_cover/1e7:.1f} Cr while "
                    f"the household's annual income is ₹{annual_income/1e7:.2f} Cr. "
                    f"Industry rule of thumb is at least 10× income (₹{10*annual_income/1e7:.1f} Cr) "
                    f"for working-age earners. Is the existing cover intentionally "
                    f"low, or should we plan to top it up?"
                ),
            })

    return findings


def format_anomalies_for_agent(anomalies: list[dict[str, Any]]) -> str:
    """Render anomaly findings into a string the chat agent can read and
    decide what to ask. Sorted high → medium → low."""
    if not anomalies:
        return ""
    order = {"high": 0, "medium": 1, "low": 2}
    sorted_a = sorted(anomalies, key=lambda x: order.get(x.get("severity", "low"), 2))
    lines = ["", "ANOMALIES DETECTED IN UPLOAD — ASK THE USER BEFORE NARRATING SUCCESS:"]
    for i, a in enumerate(sorted_a, 1):
        sev = a.get("severity", "?").upper()
        cat = a.get("category", "?")
        lines.append(f"  {i}. [{sev}/{cat}] {a.get('message', '')}")
        lines.append(f"     → ASK: {a.get('question', '')}")
    return "\n".join(lines)
