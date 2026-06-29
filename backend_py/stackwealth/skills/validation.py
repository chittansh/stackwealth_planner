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
        # Goal with NO cost — neither today's cost nor a target amount. The firm
        # model sizes its future value off today's cost (E column), so a costless
        # goal computes to ₹0 and is silently dropped from funding. Retirement is
        # excluded — its corpus is sized from expenses, not a goal target.
        today_c = _num(getattr(goal, "today_cost", None))
        target_c = _num(getattr(goal, "target_amount", None))
        is_retirement = (getattr(goal, "kind", "") or "").lower() == "retirement"
        has_cost = (today_c and today_c > 0) or (target_c and target_c > 0)
        if not is_retirement and not has_cost:
            add("medium", "completeness", f"financial_goals[{goal.goal_name}].today_cost",
                None,
                f"Goal '{goal.goal_name}' has no cost (no today's cost and no target "
                f"amount) — the firm model sizes it to ₹0, so it's silently dropped "
                f"from funding.",
                f"The goal '{goal.goal_name}' came through with no cost attached. What "
                f"does it cost in today's rupees? Without a figure I can't size or fund "
                f"it — right now it's being ignored entirely.")
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

    # 2i. One-off windfall mis-routed to RECURRING income. A bonus / expected
    # windfall / sale captured as "other income" inflates EVERY month's income
    # (and the whole projection) — it belongs in assumptions.lumpsum_events. We
    # flag "other income" that is as large as, or larger than, salary.
    inc = plan.income_details
    if inc:
        salary = (_num(getattr(inc, "client_salary_in_hand", None)) or 0) + \
                 (_num(getattr(inc, "spouse_salary_in_hand", None)) or 0)
        for fld in ("client_other_income", "spouse_other_income"):
            oth = _num(getattr(inc, fld, None))
            if oth and oth > 0 and oth >= max(salary, 100_000):
                add("medium", "income", f"income_details.{fld}", oth,
                    f"{fld} is ₹{int(oth):,}/mo — as large as or larger than salary. "
                    f"A one-off bonus / expected windfall / sale captured here inflates "
                    f"every month's income; it should be a one-time lumpsum event.",
                    f"There's ₹{int(oth):,}/mo logged as '{fld.replace('_', ' ')}'. Is "
                    f"that a steady recurring stream, or a one-off (bonus / expected "
                    f"windfall / sale) that should be a single lumpsum event in a given "
                    f"year rather than monthly income?")

    return out


# ── 3. Cross-field consistency — abnormalities visible only by comparing ───
#     fields against each other or against plausible bounds. ──────────────────


def _check_consistency(plan: PlanState) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    yr = _current_year()

    def add(severity, category, field, value, message, question):
        out.append({"kind": "consistency", "severity": severity, "category": category,
                    "field": field, "value": value, "message": message, "question": question})

    fsi = plan.freedom_score_inputs
    pd = plan.personal_details
    p0 = _person0(plan)
    income = (_num(fsi.monthly_income) if fsi else None) or 0.0
    expenses = (_num(fsi.monthly_expenses) if fsi else None) or 0.0

    dob = (pd.date_of_birth if pd else None) or (p0.date_of_birth if p0 else None)
    cur_age = _age_from_dob(dob)
    if cur_age is None and fsi:
        cur_age = _num(fsi.age)
    retire_age = _num((pd.retirement_age_target if pd else None)
                      or (p0.retirement_age if p0 else None))

    # A. Age implied by DOB outside a plausible client range.
    if cur_age is not None and (cur_age < 18 or cur_age > 100):
        add("high", "range", "personal_details.date_of_birth", cur_age,
            f"Date of birth implies current age {int(cur_age)} — outside 18–100.",
            f"The date of birth on file works out to age {int(cur_age)} today, which "
            f"looks wrong. What's the correct date of birth?")

    # B. Retirement age vs current age.
    if cur_age is not None and retire_age is not None and 0 < retire_age < 110:
        if retire_age <= cur_age:
            add("high", "retirement", "personal_details.retirement_age_target", retire_age,
                f"Retirement age {int(retire_age)} is at/below current age {int(cur_age)} "
                f"— the client is already at/past retirement.",
                f"Retirement age ({int(retire_age)}) is the same as or below the client's "
                f"current age ({int(cur_age)}). Is the client already retired, or should "
                f"the retirement age be later?")
        elif retire_age - cur_age > 45:
            add("medium", "retirement", "personal_details.retirement_age_target", retire_age,
                f"Retirement is {int(retire_age - cur_age)} years away — unusually long.",
                f"This plans for retirement {int(retire_age - cur_age)} years out (at age "
                f"{int(retire_age)}). Is that right?")

    # C. Income line items don't sum to the headline monthly income.
    inc = plan.income_details
    if inc and income > 0:
        det = sum((_num(getattr(inc, f, None)) or 0) for f in (
            "client_salary_in_hand", "spouse_salary_in_hand", "client_business_income",
            "spouse_business_income", "client_rental_income", "spouse_rental_income",
            "client_other_income", "spouse_other_income"))
        if det > 0 and abs(det - income) > max(0.2 * income, 5000):
            add("medium", "income", "income_details",
                {"detail_total": round(det), "headline": round(income)},
                f"Income line items sum to ₹{int(det):,}/mo but headline income is "
                f"₹{int(income):,}/mo — they don't reconcile.",
                f"The individual income lines add up to ₹{int(det):,}/mo, but household "
                f"monthly income is recorded as ₹{int(income):,}/mo. Which is correct?")

    # D. Implausibly high monthly income (annual entered as monthly?).
    if income > 5_000_000:
        add("low", "range", "freedom_score_inputs.monthly_income", income,
            f"Monthly income ₹{int(income):,} is very high — confirm it's monthly.",
            f"Monthly income reads ₹{int(income):,} — unusually high. Is that per month, "
            f"or did an annual figure get entered as monthly?")

    # E. Expenses dwarf income.
    if income > 0 and expenses > 3 * income:
        add("medium", "expense", "freedom_score_inputs.monthly_expenses", expenses,
            f"Monthly expenses ₹{int(expenses):,} are >3× income ₹{int(income):,}.",
            f"Monthly expenses (₹{int(expenses):,}) are more than three times income "
            f"(₹{int(income):,}). Is the expense figure annual, or is income understated?")

    # F. Loans — negative balances, missing EMI/balance, over-leverage.
    loans = plan.loans_liabilities
    total_emi = 0.0
    if loans:
        for key, label in (("home_loan", "Home loan"), ("car_loan", "Car loan"),
                           ("personal_loan", "Personal loan"), ("credit_card_dues", "Credit card")):
            blk = getattr(loans, key, None)
            if not blk:
                continue
            out_amt = _num(getattr(blk, "outstanding_amount", None))
            e = _num(getattr(blk, "emi", None))
            if out_amt is not None and out_amt < 0:
                add("high", "range", f"loans_liabilities.{key}.outstanding_amount", out_amt,
                    f"{label} outstanding is negative (₹{int(out_amt):,}).",
                    f"The {label.lower()} outstanding came through negative — sign error?")
            if e:
                total_emi += e
            if out_amt and out_amt > 0 and not e:
                add("medium", "data", f"loans_liabilities.{key}.emi", None,
                    f"{label} has a balance (₹{int(out_amt):,}) but no EMI — its repayment "
                    f"can't be modelled.",
                    f"There's a {label.lower()} balance of ₹{int(out_amt):,} but no EMI on "
                    f"file. What's the monthly EMI (and rough interest rate)?")
            if e and e > 0 and not out_amt:
                add("low", "data", f"loans_liabilities.{key}.outstanding_amount", None,
                    f"{label} has an EMI (₹{int(e):,}) but no outstanding balance.",
                    f"There's a {label.lower()} EMI of ₹{int(e):,}/mo but no outstanding "
                    f"balance — roughly how much is still owed?")
    if income > 0 and total_emi > 0.5 * income:
        add("high", "debt", "freedom_score_inputs.monthly_emi", round(total_emi),
            f"Total EMIs ₹{int(total_emi):,}/mo exceed 50% of income ₹{int(income):,}/mo.",
            f"Loan EMIs total ₹{int(total_emi):,}/mo — over half of monthly income. That's "
            f"a heavy debt load; is it right, or are some loans already closed?")

    # G. No medical cover at all.
    ins = plan.insurance_details
    if ins and income > 0:
        h = getattr(ins, "health_insurance", None)
        f = getattr(ins, "family_floater", None)
        h_cover = (_num(getattr(h, "cover_amount", None)) if h else 0) or 0
        f_cover = (_num(getattr(f, "cover_amount", None)) if f else 0) or 0
        if h_cover + f_cover <= 0:
            add("medium", "insurance", "insurance_details.health_insurance", 0,
                "No health / medical insurance cover captured.",
                "I don't see any health or family-floater medical cover on file. Is there "
                "a health policy I'm missing, or is the family uninsured medically?")

    # H. Rate-like assumptions outside a plausible band.
    asn = plan.assumptions
    if asn:
        rate_fields: list[tuple[str, Optional[float]]] = [("assumptions.inflation", _num(asn.inflation))]
        for grp, names in (("growth", ("cash", "investment", "real_estate", "vehicle")),
                           ("income_growth", ("employment", "business", "rental", "other"))):
            obj = getattr(asn, grp, None)
            if obj is not None:
                for n in names:
                    rate_fields.append((f"assumptions.{grp}.{n}", _num(getattr(obj, n, None))))
        for field, rv in rate_fields:
            if rv is not None and (rv > 0.5 or rv < -0.5):
                add("medium", "range", field, rv,
                    f"{field} = {rv} is outside a plausible annual rate (−0.50 to 0.50).",
                    f"The assumption {field.split('.')[-1]} is {rv} ({rv*100:.0f}%/yr) — "
                    f"outside the normal range. Is it entered correctly?")

    # I. Existing SIPs exceed income.
    mi = plan.monthly_investments
    if mi and income > 0:
        sip = sum((_num(getattr(mi, f, None)) or 0) for f in
                  ("mutual_fund_sip", "nps", "ppf", "rd", "direct_equity", "insurance_premium", "other"))
        if sip > income:
            add("medium", "surplus", "monthly_investments", round(sip),
                f"Monthly SIPs ₹{int(sip):,} exceed monthly income ₹{int(income):,}.",
                f"Existing monthly SIPs add up to ₹{int(sip):,} — more than monthly income "
                f"(₹{int(income):,}). Are these actually running, or aspirational?")

    # J. Duplicate goals + goals beyond the client's projected lifetime.
    life_year = None
    if cur_age is not None:
        le = (p0.life_expectancy if p0 else None) or 85
        if le:
            life_year = yr + int(le - cur_age)
    seen: dict[str, int] = {}
    for g in plan.financial_goals or []:
        nm = (g.goal_name or "").strip().lower()
        if nm:
            seen[nm] = seen.get(nm, 0) + 1
        ty = _num(getattr(g, "target_year", None))
        if ty and life_year and ty > life_year + 1 and (g.kind or "").lower() != "retirement":
            add("low", "range", f"financial_goals[{g.goal_name}].target_year", int(ty),
                f"Goal '{g.goal_name}' is dated {int(ty)} — beyond the client's projected "
                f"lifetime (~{life_year}).",
                f"The goal '{g.goal_name}' targets {int(ty)}, past the client's expected "
                f"lifetime (~{life_year}). Is the year right?")
    for nm, cnt in seen.items():
        if cnt > 1:
            add("low", "data", f"financial_goals[{nm}]", cnt,
                f"A goal named '{nm}' appears {cnt} times — possible duplicate.",
                f"There are {cnt} goals named '{nm}'. Intentional (e.g. two children) or a "
                f"duplicate to merge?")

    # K. Labelled input fields with no standard slot — captured so nothing is
    # dropped; surface them so the RM can place anything that matters.
    extras = getattr(plan, "extra_inputs", None) or []
    if extras:
        labels = ", ".join(str(e.get("label", "")).strip()
                           for e in extras[:6] if isinstance(e, dict) and e.get("label"))
        add("low", "completeness", "extra_inputs", len(extras),
            f"{len(extras)} labelled field(s) in the upload have no standard plan slot "
            f"and were captured separately: {labels}.",
            f"The upload had {len(extras)} field(s) that don't map to the plan ({labels}). "
            f"Do any of these matter for the plan — e.g. dependents to provide for, a second "
            f"income, a one-off note — so I can place them?")

    return out


# ── Public entry point ─────────────────────────────────────────────────────


def validate_plan(plan: PlanState) -> dict[str, Any]:
    """Run the full post-extraction validation. Returns a structured report the
    `validate_inputs` tool persists and the chat agent reads to ask the RM.

    `ok` is True when nothing high-severity surfaced — i.e. the plan is safe to
    narrate without a clarifying question first."""
    required = _check_required_inputs(plan)
    suspect = _check_suspect_values(plan)
    consistency = _check_consistency(plan)
    anomalies = [{**a, "kind": "anomaly"} for a in detect_plan_anomalies(plan)]

    # De-dupe only EXACT duplicates (same field AND same message) so the
    # consistency and anomaly passes don't print the identical line twice. A
    # coarser key would suppress genuinely distinct findings — e.g. two lumpsums
    # in the same year, or a goal flagged for both "no cost" and "past year" —
    # which is the opposite of what a validation layer should do.
    findings = required + suspect + consistency + anomalies
    seen_keys: set[tuple] = set()
    deduped: list[dict[str, Any]] = []
    for f in findings:
        key = (f.get("field"), f.get("message"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(f)
    findings = deduped
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
        "consistency": consistency,
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
