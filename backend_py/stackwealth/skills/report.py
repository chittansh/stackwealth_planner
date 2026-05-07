"""
Server-side institutional report generator.

Builds a multi-page, text-heavy financial review HTML from PlanState and
prints it to PDF via Playwright. Modeled on the Stackwealth portfolio-review
template:
   1. Executive Summary (key metrics + recommendations)
   2. Profile & Income/Expenses
   3. Net Worth & Holdings
   4. Insurance & Liabilities
   5. Financial Goals
   6. Risk Profile
   7. Allocation (Strategic + Recommended)
   8. Cash Flow Projection
   9. Tax Harvesting
  10. Freedom Score Scorecard
  11. Recommendations & 12-Month Roadmap
  12. Disclaimer

If Playwright isn't available, returns the same HTML (browser print works).
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from .. import config
from ..db import get_plan
from ..types import PlanState


# ── Helpers ────────────────────────────────────────────────────────────────


def _fmt_inr(n: float | int | None) -> str:
    """Indian-style grouping, no decimals. ₹1,25,000 not ₹125,000."""
    if n is None or not isinstance(n, (int, float)):
        return "—"
    n = round(n)
    if n < 0:
        return "-" + _fmt_inr(-n)
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return f"₹{','.join(parts)},{last3}"


def _fmt_lakhs(n: float | int | None) -> str:
    if n is None or not isinstance(n, (int, float)) or n == 0:
        return "—"
    if abs(n) >= 1_00_00_000:
        return f"₹{n / 1_00_00_000:.2f} Cr"
    if abs(n) >= 1_00_000:
        return f"₹{n / 1_00_000:.2f} L"
    return _fmt_inr(n)


def _fmt_pct(n: float | None, decimals: int = 1) -> str:
    if n is None or not isinstance(n, (int, float)):
        return "—"
    return f"{n:.{decimals}f}%"


def _h(s: Any) -> str:
    if s is None:
        return "—"
    return html.escape(str(s))


def _yes(v: Any) -> str:
    return "Yes" if v else "No"


def _sum_optionals(o: Any) -> float:
    if hasattr(o, "model_dump"):
        o = o.model_dump()
    if not isinstance(o, dict):
        return 0.0
    return sum(v for v in o.values() if isinstance(v, (int, float)))


# ── HTML template ──────────────────────────────────────────────────────────


CSS = """
@page { size: A4; margin: 14mm 14mm 18mm 14mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: 'Helvetica Neue', Arial, sans-serif;
  color: #18181b;
  font-size: 10.5pt;
  line-height: 1.45;
}
.page { page-break-after: always; padding-bottom: 18mm; position: relative; }
.page:last-child { page-break-after: auto; }
h1 { font-size: 22pt; margin: 0 0 4mm; font-weight: 700; letter-spacing: -0.01em; }
h2 { font-size: 15pt; margin: 8mm 0 3mm; font-weight: 600; border-bottom: 1px solid #e4e4e7; padding-bottom: 1.5mm; }
h3 { font-size: 12pt; margin: 5mm 0 2mm; font-weight: 600; color: #27272a; }
h4 { font-size: 11pt; margin: 3mm 0 1.5mm; font-weight: 600; color: #3f3f46; }
p { margin: 0 0 2.5mm; }
ul, ol { margin: 0 0 3mm 5mm; padding: 0; }
li { margin: 0 0 1mm; }
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 9.8pt; }
th, td { padding: 2mm 2.5mm; border: 1px solid #e4e4e7; text-align: left; vertical-align: top; }
th { background: #fafafa; font-weight: 600; color: #3f3f46; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.muted { color: #71717a; font-size: 9.5pt; }
.headline { background: #f4f4f5; padding: 4mm 5mm; border-left: 3px solid #18181b; margin: 3mm 0 5mm; }
.headline h1 { font-size: 18pt; }
.kbox { display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; margin: 3mm 0; }
.kcell { background: #fafafa; padding: 3mm 4mm; border: 1px solid #e4e4e7; border-radius: 1.5mm; }
.kcell .label { font-size: 9pt; color: #71717a; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 1mm; }
.kcell .val { font-size: 13pt; font-weight: 600; color: #18181b; }
.kcell .note { font-size: 9pt; color: #52525b; margin-top: 1mm; }
.takeaway { background: #fefce8; padding: 3mm 4mm; border-left: 3px solid #ca8a04; margin: 3mm 0 4mm; font-size: 10pt; }
.takeaway strong { color: #713f12; }
.bad { color: #b91c1c; }
.good { color: #15803d; }
.warn { color: #b45309; }
/* No in-content footer — Playwright's footer_template handles every page. */
.cover {
  display: flex; flex-direction: column; justify-content: center;
  min-height: 240mm;
}
.cover .brand { font-size: 11pt; color: #71717a; letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 4mm; }
.cover h1 { font-size: 30pt; line-height: 1.1; margin-bottom: 2mm; }
.cover .sub { font-size: 13pt; color: #52525b; margin-bottom: 6mm; }
.cover .meta { font-size: 10.5pt; color: #3f3f46; }
.disclaimer { font-size: 8.5pt; color: #71717a; line-height: 1.45; margin-top: 5mm; }
.scorecard td { padding: 1.5mm 3mm; }
.score-bar { height: 4mm; background: #e4e4e7; border-radius: 1mm; overflow: hidden; }
.score-bar > div { height: 100%; background: #18181b; }
.pill { display: inline-block; padding: 0.5mm 2mm; border-radius: 1.5mm; background: #f4f4f5; font-size: 9pt; color: #3f3f46; }
"""


def _footer(_page_num: int) -> str:
    """No-op — kept so call sites compile. Real footer is injected per printed
    page via Playwright's footer_template."""
    return ""


def _cover_page(plan: PlanState) -> str:
    name = plan.personal_details.full_name or plan.household_id
    today = datetime.now().strftime("%B %d, %Y")
    return f"""<section class="page cover">
  <div class="brand">Stackwealth Research Desk</div>
  <h1>Comprehensive Financial Plan</h1>
  <div class="sub">Institutional-Grade Household Review</div>
  <div class="meta">
    <p><strong>Client:</strong> {_h(name)}</p>
    <p><strong>Household ID:</strong> {_h(plan.household_id)}</p>
    <p><strong>Date:</strong> {today}</p>
    <p><strong>Prepared by:</strong> Stackwealth Research Desk</p>
  </div>
  {_footer(1)}
</section>"""


def _executive_summary(plan: PlanState, page_num: int) -> str:
    pd = plan.personal_details
    fsi = plan.freedom_score_inputs
    fs = plan.computed.freedom_score
    nw = plan.computed.net_worth
    headline = plan.computed.headline_amount_at_horizon
    horizon = plan.computed.horizon_years
    monthly_income = (fsi.monthly_income or 0)
    monthly_expenses = (fsi.monthly_expenses or 0)
    monthly_emi = (fsi.monthly_emi or 0)
    surplus = monthly_income - monthly_expenses - monthly_emi
    surplus_rate = (surplus / monthly_income * 100) if monthly_income else 0
    age = fsi.age or "—"
    final_score = fs.final_score if fs else None
    profile = "—"
    if final_score is not None:
        profile = "Strong" if final_score >= 70 else "Moderate" if final_score >= 50 else "Needs Attention"

    return f"""<section class="page">
  <div class="headline"><h1>1. Executive Summary</h1></div>
  <p>This report provides a comprehensive review of <strong>{_h(pd.full_name or plan.household_id)}'s</strong>
  household financial plan as of {datetime.now().strftime('%B %d, %Y')}. It analyzes income, expenses,
  holdings, liabilities, insurance coverage, and goals to surface specific gaps and the actions needed to
  close them. Every numeric figure in this report is sourced from the canonical PlanState; nothing is
  inferred without the underlying inputs.</p>

  <h3>Household Snapshot</h3>
  <div class="kbox">
    <div class="kcell"><div class="label">Age</div><div class="val">{_h(age)}</div><div class="note">Years</div></div>
    <div class="kcell"><div class="label">City</div><div class="val">{_h(pd.city_of_residence or '—')}</div><div class="note">{_h(pd.city_type or '—')}</div></div>
    <div class="kcell"><div class="label">Marital Status</div><div class="val">{_h(pd.marital_status or '—')}</div><div class="note">Dependents: {_h(pd.dependents or 0)}</div></div>
    <div class="kcell"><div class="label">Retirement Target</div><div class="val">{_h(pd.retirement_age_target or '—')}</div><div class="note">Years</div></div>
  </div>

  <h3>Key Financial Metrics</h3>
  <table>
    <tr><th>Metric</th><th class="num">Value</th><th>Insight</th></tr>
    <tr><td>Monthly Take-home</td><td class="num">{_fmt_inr(monthly_income)}</td><td>Total household inflow</td></tr>
    <tr><td>Monthly Fixed Expenses</td><td class="num">{_fmt_inr(monthly_expenses)}</td><td>{_fmt_pct((monthly_expenses / monthly_income * 100) if monthly_income else 0)} of income</td></tr>
    <tr><td>Monthly EMI Burden</td><td class="num">{_fmt_inr(monthly_emi)}</td><td>{_fmt_pct((monthly_emi / monthly_income * 100) if monthly_income else 0)} of income</td></tr>
    <tr><td>Monthly Surplus</td><td class="num">{_fmt_inr(surplus)}</td><td>{_fmt_pct(surplus_rate)} savings rate</td></tr>
    <tr><td>Net Worth (Today)</td><td class="num">{_fmt_lakhs(nw.total)}</td><td>Assets minus liabilities</td></tr>
    <tr><td>Liquid Assets</td><td class="num">{_fmt_lakhs(nw.liquid)}</td><td>Cash + breakable FDs</td></tr>
    <tr><td>Investment Portfolio</td><td class="num">{_fmt_lakhs(fsi.portfolio_current_value or 0)}</td><td>MFs + equities + FI</td></tr>
    <tr><td>Total Debt Outstanding</td><td class="num">{_fmt_lakhs(nw.debts_total)}</td><td>Home + auto + personal + credit</td></tr>
    <tr><td>Freedom Score</td><td class="num">{_fmt_pct(final_score, 1) if final_score is not None else '—'}</td><td>{_h(profile)} (out of 100)</td></tr>
    <tr><td>{horizon}-yr Projection</td><td class="num">{_fmt_lakhs(headline)}</td><td>Net worth at age {(fsi.age or 30) + horizon}</td></tr>
  </table>

  <h3>Top Recommendations</h3>
  {_top_recommendations(plan)}
  {_footer(page_num)}
</section>"""


def _top_recommendations(plan: PlanState) -> str:
    fs = plan.computed.freedom_score
    recs: list[str] = []
    if fs:
        pillars = fs.pillars
        ranked = sorted(
            [
                ("Liquidity", pillars.liquidity, "Build emergency fund equal to 6 months of expenses; park in high-yield savings or sweep-FD."),
                ("Debt", pillars.debt, "Reduce EMI exposure below 35% of monthly income; prepay highest-interest loans first."),
                ("Investment", pillars.investment, "Ramp up SIP to align portfolio with annual income × 5; tilt to equity per recommended allocation."),
                ("Discipline", pillars.discipline, "Automate SIPs and lock in savings rate ≥ 30%; review every quarter against the cash-flow plan."),
                ("Risk", pillars.risk, "Top up term cover to 10× annual income (city-adjusted); ensure family floater covers all dependents."),
            ],
            key=lambda x: x[1],
        )
        for name, score, action in ranked[:3]:
            recs.append(f"<li><strong>{name} ({score:.0f}/100):</strong> {action}</li>")
    if not plan.computed.risk_profile:
        recs.append(
            "<li><strong>Risk profile not set:</strong> Run the 3-question risk assessment in chat — gates allocation, tax-harvest, and Monte Carlo.</li>"
        )
    if not plan.financial_goals:
        recs.append(
            "<li><strong>No goals captured:</strong> Add at least one goal (retirement, child education, home) so the projection is meaningful.</li>"
        )
    if not recs:
        recs.append("<li>Plan is in good shape — continue reviewing quarterly.</li>")
    return f"<ol>{''.join(recs)}</ol>"


def _profile_income_expenses(plan: PlanState, page_num: int) -> str:
    pd = plan.personal_details
    inc = plan.income_details
    exp = plan.monthly_expenses
    inv = plan.monthly_investments

    income_rows = [
        ("Client salary", inc.client_salary_in_hand),
        ("Spouse salary", inc.spouse_salary_in_hand),
        ("Client business", inc.client_business_income),
        ("Spouse business", inc.spouse_business_income),
        ("Client rental", inc.client_rental_income),
        ("Spouse rental", inc.spouse_rental_income),
        ("Client other", inc.client_other_income),
        ("Spouse other", inc.spouse_other_income),
    ]
    income_html = "".join(
        f'<tr><td>{label}</td><td class="num">{_fmt_inr(amt)}</td></tr>'
        for label, amt in income_rows
        if amt and amt > 0
    ) or '<tr><td colspan="2" class="muted">No income captured.</td></tr>'

    exp_rows = [
        ("Household", exp.household_expenses),
        ("Rent / EMI", exp.rent_or_emi),
        ("Groceries", exp.groceries),
        ("Utilities", exp.utilities),
        ("School fees", exp.school_fees),
        ("Insurance premium", exp.insurance_premium),
        ("Medical", exp.medical),
        ("Travel / Lifestyle", exp.travel_or_lifestyle),
        ("Existing SIPs", exp.sip_investments),
        ("Other EMIs", exp.other_emis),
    ]
    exp_html = "".join(
        f'<tr><td>{label}</td><td class="num">{_fmt_inr(amt)}</td></tr>'
        for label, amt in exp_rows
        if amt and amt > 0
    ) or '<tr><td colspan="2" class="muted">No expenses captured.</td></tr>'

    inv_rows = [
        ("Mutual fund SIP", inv.mutual_fund_sip),
        ("NPS", inv.nps),
        ("PPF", inv.ppf),
        ("RD", inv.rd),
        ("Direct equity", inv.direct_equity),
        ("Insurance premium", inv.insurance_premium),
        ("Other", inv.other),
    ]
    inv_html = "".join(
        f'<tr><td>{label}</td><td class="num">{_fmt_inr(amt)}</td></tr>'
        for label, amt in inv_rows
        if amt and amt > 0
    ) or '<tr><td colspan="2" class="muted">No monthly investments captured.</td></tr>'

    total_inc = sum(v for v in (
        inc.client_salary_in_hand, inc.spouse_salary_in_hand,
        inc.client_business_income, inc.spouse_business_income,
        inc.client_rental_income, inc.spouse_rental_income,
        inc.client_other_income, inc.spouse_other_income
    ) if isinstance(v, (int, float)))
    total_exp = _sum_optionals(exp)
    total_inv = _sum_optionals(inv)
    surplus = total_inc - total_exp - total_inv

    return f"""<section class="page">
  <h2>2. Profile, Income & Expenses</h2>

  <h3>Personal Details</h3>
  <table>
    <tr><th>Full name</th><td>{_h(pd.full_name)}</td><th>DOB</th><td>{_h(pd.date_of_birth)}</td></tr>
    <tr><th>City</th><td>{_h(pd.city_of_residence)} ({_h(pd.city_type)})</td><th>Occupation</th><td>{_h(pd.occupation)}</td></tr>
    <tr><th>Marital</th><td>{_h(pd.marital_status)}</td><th>Dependents</th><td>{_h(pd.dependents or 0)}</td></tr>
    <tr><th>Retirement target</th><td>{_h(pd.retirement_age_target or '—')}</td><th>Spouse</th><td>{_h(pd.spouse_name_and_age or '—')}</td></tr>
  </table>

  <h3>Monthly Income</h3>
  <table>
    <tr><th>Source</th><th class="num">Monthly (₹)</th></tr>
    {income_html}
    <tr><th>Total Inflow</th><th class="num">{_fmt_inr(total_inc)}</th></tr>
  </table>

  <h3>Monthly Expenses</h3>
  <table>
    <tr><th>Category</th><th class="num">Monthly (₹)</th></tr>
    {exp_html}
    <tr><th>Total Outflow</th><th class="num">{_fmt_inr(total_exp)}</th></tr>
  </table>

  <h3>Monthly Investment Outflow</h3>
  <table>
    <tr><th>Vehicle</th><th class="num">Monthly (₹)</th></tr>
    {inv_html}
    <tr><th>Total Investing</th><th class="num">{_fmt_inr(total_inv)}</th></tr>
  </table>

  <div class="takeaway">
    <strong>Cash-flow takeaway:</strong> Monthly surplus is <strong>{_fmt_inr(surplus)}</strong>
    ({_fmt_pct((surplus / total_inc * 100) if total_inc else 0)} of inflow) after fixed expenses and existing investments.
    {'A surplus this large supports an aggressive SIP step-up.' if surplus > total_inc * 0.30 else 'Surplus is moderate — focus on essentials before raising risk.'}
  </div>
  {_footer(page_num)}
</section>"""


def _net_worth_holdings(plan: PlanState, page_num: int) -> str:
    nw = plan.computed.net_worth
    fsi = plan.freedom_score_inputs
    lc = plan.liquid_capital

    mf_total = sum((h.current_value or 0) for h in plan.mutual_funds)
    eq_total = sum((h.current_value or 0) for h in plan.equity_stocks)
    fi_total = sum((h.current_value or 0) for h in plan.fixed_income)

    def _money_table(rows: list[tuple[str, float | None]]) -> str:
        body = "".join(
            f'<tr><td>{_h(label)}</td><td class="num">{_fmt_inr(amt) if amt else "—"}</td></tr>'
            for label, amt in rows if amt
        )
        return body or '<tr><td colspan="2" class="muted">None captured.</td></tr>'

    liquid_rows = [
        ("Savings account balance", lc.savings_account_balance),
        ("Idle cash for investment", lc.idle_cash_for_investment),
        ("FD breakable for investment", lc.fd_breakable_for_investment),
        ("Bonus expected for investment", lc.bonus_expected_for_investment),
    ]

    mf_rows_html = "".join(
        f'<tr><td>{_h(h.fund_name or h.id[:8])}</td>'
        f'<td>{_h(h.isin or "—")}</td>'
        f'<td>{_h(h.registrar or "—")}</td>'
        f'<td class="num">{_fmt_inr(h.current_value)}</td>'
        f'<td class="num">{_h(h.closing_units or "—")}</td>'
        f'</tr>'
        for h in plan.mutual_funds
    ) or '<tr><td colspan="5" class="muted">No mutual fund holdings captured.</td></tr>'

    eq_rows_html = "".join(
        f'<tr><td>{_h(h.stock_name or h.id[:8])}</td>'
        f'<td>{_h(h.isin or "—")}</td>'
        f'<td class="num">{_h(h.quantity or "—")}</td>'
        f'<td class="num">{_fmt_inr(h.last_traded_price)}</td>'
        f'<td class="num">{_fmt_inr(h.current_value)}</td>'
        f'<td>{_h((h.long_term_or_trading or "long_term").replace("_", " "))}</td>'
        f'</tr>'
        for h in plan.equity_stocks
    ) or '<tr><td colspan="6" class="muted">No equity holdings captured.</td></tr>'

    fi_rows_html = "".join(
        f'<tr><td>{_h(h.instrument)}</td>'
        f'<td class="num">{_fmt_inr(h.invested_amount)}</td>'
        f'<td class="num">{_fmt_inr(h.current_value)}</td>'
        f'<td>{_h(h.maturity_date or "—")}</td>'
        f'</tr>'
        for h in plan.fixed_income
    ) or '<tr><td colspan="4" class="muted">No fixed-income holdings captured.</td></tr>'

    return f"""<section class="page">
  <h2>3. Net Worth & Holdings</h2>

  <h3>Aggregate Net Worth</h3>
  <table>
    <tr><th>Bucket</th><th class="num">Amount</th><th>Note</th></tr>
    <tr><td>Liquid (cash + breakable FD)</td><td class="num">{_fmt_lakhs(nw.liquid)}</td><td>Available within 30 days</td></tr>
    <tr><td>Non-liquid (investments)</td><td class="num">{_fmt_lakhs(nw.non_liquid)}</td><td>Equities + MFs + fixed income</td></tr>
    <tr><td>Total assets</td><td class="num">{_fmt_lakhs(nw.assets_total)}</td><td>Liquid + non-liquid</td></tr>
    <tr><td>Total debt outstanding</td><td class="num bad">{_fmt_lakhs(nw.debts_total)}</td><td>Home + auto + personal + credit</td></tr>
    <tr><th>Net Worth Today</th><th class="num">{_fmt_lakhs(nw.total)}</th><th>—</th></tr>
  </table>

  <h3>Liquid Capital Detail</h3>
  <table><tr><th>Account</th><th class="num">Balance</th></tr>{_money_table(liquid_rows)}</table>

  <h3>Mutual Funds ({len(plan.mutual_funds)} holdings | {_fmt_lakhs(mf_total)} total)</h3>
  <table>
    <tr><th>Fund</th><th>ISIN</th><th>Registrar</th><th class="num">Current</th><th class="num">Units</th></tr>
    {mf_rows_html}
  </table>

  <h3>Equity Holdings ({len(plan.equity_stocks)} stocks | {_fmt_lakhs(eq_total)} total)</h3>
  <table>
    <tr><th>Stock</th><th>ISIN</th><th class="num">Qty</th><th class="num">LTP</th><th class="num">Current</th><th>Type</th></tr>
    {eq_rows_html}
  </table>

  <h3>Fixed Income ({len(plan.fixed_income)} instruments | {_fmt_lakhs(fi_total)} total)</h3>
  <table>
    <tr><th>Instrument</th><th class="num">Invested</th><th class="num">Current</th><th>Maturity</th></tr>
    {fi_rows_html}
  </table>
  {_footer(page_num)}
</section>"""


def _insurance_liabilities(plan: PlanState, page_num: int) -> str:
    ins = plan.insurance_details
    loans = plan.loans_liabilities

    def _ins_row(label: str, b: Any) -> str:
        if not b:
            return f'<tr><td>{label}</td><td class="muted" colspan="3">— Not on file —</td></tr>'
        return (
            f"<tr><td>{label}</td>"
            f"<td>{_h(b.company)}</td>"
            f'<td class="num">{_fmt_lakhs(b.cover_amount)}</td>'
            f'<td class="num">{_fmt_inr(b.annual_premium)}</td>'
            f"</tr>"
        )

    def _loan_row(label: str, b: Any) -> str:
        if not b or not (b.outstanding_amount or b.emi):
            return f'<tr><td>{label}</td><td class="muted" colspan="4">— Not on file —</td></tr>'
        return (
            f"<tr><td>{label}</td>"
            f'<td class="num">{_fmt_lakhs(b.outstanding_amount)}</td>'
            f'<td class="num">{_fmt_inr(b.emi)}</td>'
            f'<td class="num">{_fmt_pct(b.interest_rate)}</td>'
            f'<td class="num">{_h(b.tenure_left or "—")}</td>'
            f"</tr>"
        )

    fs = plan.computed.freedom_score
    req_life = fs.required_life_cover if fs else 0
    req_med = fs.required_medical_cover if fs else 0
    have_life = (ins.term_plan and ins.term_plan.cover_amount) or 0
    have_med = max(
        (ins.health_insurance and ins.health_insurance.cover_amount) or 0,
        (ins.family_floater and ins.family_floater.cover_amount) or 0,
    )

    return f"""<section class="page">
  <h2>4. Insurance Coverage & Liabilities</h2>

  <h3>Insurance Cover</h3>
  <table>
    <tr><th>Policy</th><th>Insurer</th><th class="num">Cover</th><th class="num">Annual Premium</th></tr>
    {_ins_row("Term plan", ins.term_plan)}
    {_ins_row("Health (individual)", ins.health_insurance)}
    {_ins_row("Family floater", ins.family_floater)}
    {_ins_row("ULIP / Endowment", ins.ulip_or_endowment)}
  </table>

  <h3>Coverage Gap Analysis</h3>
  <table>
    <tr><th>Need</th><th class="num">Required</th><th class="num">Currently held</th><th class="num">Gap</th></tr>
    <tr><td>Life cover (term)</td><td class="num">{_fmt_lakhs(req_life)}</td><td class="num">{_fmt_lakhs(have_life)}</td><td class="num bad">{_fmt_lakhs(max(0, req_life - have_life)) if req_life else "—"}</td></tr>
    <tr><td>Medical cover</td><td class="num">{_fmt_lakhs(req_med)}</td><td class="num">{_fmt_lakhs(have_med)}</td><td class="num bad">{_fmt_lakhs(max(0, req_med - have_med)) if req_med else "—"}</td></tr>
  </table>

  <div class="takeaway">
    <strong>Insurance takeaway:</strong> {'Coverage is adequate.' if have_life >= req_life and have_med >= req_med else 'There is a measurable gap. Top up term cover and/or medical floater before adding investment risk.'}
  </div>

  <h3>Loans & Liabilities</h3>
  <table>
    <tr><th>Loan</th><th class="num">Outstanding</th><th class="num">EMI</th><th class="num">Rate</th><th class="num">Tenure left (yrs)</th></tr>
    {_loan_row("Home loan", loans.home_loan)}
    {_loan_row("Car loan", loans.car_loan)}
    {_loan_row("Personal loan", loans.personal_loan)}
    {_loan_row("Credit card dues", loans.credit_card_dues)}
  </table>
  {_footer(page_num)}
</section>"""


def _goals(plan: PlanState, page_num: int) -> str:
    if not plan.financial_goals:
        rows = '<tr><td colspan="6" class="muted">No goals captured. Add at least retirement + one major goal in chat.</td></tr>'
    else:
        rows = "".join(
            f"<tr>"
            f"<td>{_h(g.goal_name)}</td>"
            f'<td>{_h(g.kind.replace("_", " "))}</td>'
            f'<td class="num">{_h(g.target_year or "—")}</td>'
            f'<td class="num">{_fmt_lakhs(g.target_amount)}</td>'
            f'<td class="num">{_fmt_lakhs(g.current_allocated_amount)}</td>'
            f'<td>{_h(g.priority or "—")}</td>'
            f"</tr>"
            for g in plan.financial_goals
        )

    return f"""<section class="page">
  <h2>5. Financial Goals</h2>
  <p class="muted">Each goal drives a need-score in the risk-profile reconciliation. Targets are inflation-adjusted at the household assumption ({_fmt_pct(plan.assumptions.inflation * 100)}/yr) unless overridden.</p>
  <table>
    <tr><th>Goal</th><th>Kind</th><th class="num">Target Year</th><th class="num">Target</th><th class="num">Already Saved</th><th>Priority</th></tr>
    {rows}
  </table>
  {_footer(page_num)}
</section>"""


def _risk_allocation(plan: PlanState, page_num: int) -> str:
    rp = plan.computed.risk_profile
    al = plan.computed.allocation

    if rp:
        risk_html = f"""
    <table>
      <tr><th>Component</th><th class="num">Score</th><th>Profile</th></tr>
      <tr><td>Capacity (binding cap: {_h(rp.capacity_binding_cap)})</td><td class="num">{rp.capacity_score}</td><td>{_h(rp.capacity_profile)}</td></tr>
      <tr><td>Need (driver: {_h(rp.need_primary_goal or "—")})</td><td class="num">{rp.need_score}</td><td>{_h(rp.need_profile)}</td></tr>
      <tr><td>Willingness</td><td class="num">{rp.willingness_score}</td><td>{_h(rp.willingness_profile)}</td></tr>
      <tr><th>Recommended</th><th class="num">{rp.recommended_score}</th><th>{_h(rp.recommended_profile)}</th></tr>
    </table>
    <p><strong>Alignment:</strong> {_h(rp.alignment_status.replace("_", " "))}</p>
    {('<ul>' + ''.join(f'<li>{_h(w)}</li>' for w in rp.key_warnings) + '</ul>') if rp.key_warnings else ''}
"""
    else:
        risk_html = '<p class="muted">Risk profile not yet computed. Run the 3-question assessment in chat.</p>'

    if al:
        sa = al.strategic_allocation
        ra = al.recommended_allocation
        regime = f"{al.tactical_regime_label} ({al.tactical_regime_score:+.0f})"
        signals_html = "".join(
            f'<tr><td>{_h(k)}</td><td class="num">{v.score:+.0f}</td><td>{_h(v.reason)}</td></tr>'
            for k, v in al.signal_breakdown.items()
        )
        alloc_html = f"""
    <p><strong>Tactical regime:</strong> {regime}</p>

    <h3>Allocation Buckets</h3>
    <table>
      <tr><th>Bucket</th><th class="num">Strategic</th><th class="num">Recommended</th><th class="num">Shift</th></tr>
      <tr><td>Equity</td><td class="num">{sa.equity}%</td><td class="num">{ra.equity}%</td><td class="num">{ra.equity - sa.equity:+.0f}pp</td></tr>
      <tr><td>Debt</td><td class="num">{sa.debt}%</td><td class="num">{ra.debt}%</td><td class="num">{ra.debt - sa.debt:+.0f}pp</td></tr>
      <tr><td>Gold</td><td class="num">{sa.gold}%</td><td class="num">{ra.gold}%</td><td class="num">{ra.gold - sa.gold:+.0f}pp</td></tr>
      <tr><td>Cash</td><td class="num">{sa.cash}%</td><td class="num">{ra.cash}%</td><td class="num">{ra.cash - sa.cash:+.0f}pp</td></tr>
    </table>

    <h3>Signal Breakdown</h3>
    <table>
      <tr><th>Block</th><th class="num">Score</th><th>Reasoning</th></tr>
      {signals_html}
    </table>

    <p><strong>Sector views — overweight:</strong> {", ".join(al.sector_theme_views.overweight) or "—"}</p>
    <p><strong>Sector views — underweight:</strong> {", ".join(al.sector_theme_views.underweight) or "—"}</p>
    {'<ul>' + ''.join(f'<li>{_h(w)}</li>' for w in al.warnings) + '</ul>' if al.warnings else ''}
"""
    else:
        alloc_html = '<p class="muted">Allocation not yet computed. Set risk profile first.</p>'

    return f"""<section class="page">
  <h2>6. Risk Profile</h2>
  {risk_html}

  <h2>7. Asset Allocation</h2>
  {alloc_html}
  {_footer(page_num)}
</section>"""


def _cashflow(plan: PlanState, page_num: int) -> str:
    cf = plan.computed.cashflow
    if not cf or not cf.rows:
        body = '<tr><td colspan="6" class="muted">Cash flow projection not computed. Capture income + expenses + age, then run cashflow_project in chat.</td></tr>'
    else:
        # Render every 5th year + first 3 + last 3 to keep it readable.
        rows = cf.rows
        idx_keep = sorted(set([0, 1, 2] + list(range(4, len(rows) - 3, 5)) + [len(rows) - 3, len(rows) - 2, len(rows) - 1]))
        idx_keep = [i for i in idx_keep if 0 <= i < len(rows)]
        body = "".join(
            f"<tr>"
            f'<td class="num">{r.year}</td>'
            f'<td class="num">{r.age}</td>'
            f'<td class="num">{_fmt_lakhs(r.income)}</td>'
            f'<td class="num">{_fmt_lakhs(r.expenses)}</td>'
            f'<td class="num">{_fmt_lakhs(r.taxes)}</td>'
            f'<td class="num">{_fmt_lakhs(r.total_net_worth)}</td>'
            f"</tr>"
            for i, r in enumerate(rows) if i in idx_keep
        )

    return f"""<section class="page">
  <h2>8. Cash Flow Projection</h2>
  <p class="muted">Year-by-year inflow/outflow with inflation indexing. Rows shown every ~5 years; the first three and last three years are always included.</p>
  <table>
    <tr><th class="num">Year</th><th class="num">Age</th><th class="num">Income</th><th class="num">Expenses</th><th class="num">Taxes</th><th class="num">Net Worth</th></tr>
    {body}
  </table>
  {_footer(page_num)}
</section>"""


def _tax_freedom_scorecard(plan: PlanState, page_num: int) -> str:
    tax = plan.computed.tax
    if tax:
        gain_rows = "".join(
            f'<tr><td>{_h(s.holding_id[:12])}…</td><td class="num">{s.units:.1f}</td><td class="num">{_fmt_inr(s.expected_gain)}</td><td class="num good">{_fmt_inr(s.tax_saved)}</td></tr>'
            for s in tax.gain_harvest_suggestions[:10]
        ) or '<tr><td colspan="4" class="muted">No qualifying gain-harvest opportunities this FY.</td></tr>'
        loss_rows = "".join(
            f'<tr><td>{_h(s.holding_id[:12])}…</td><td class="num">{s.units:.1f}</td><td class="num bad">{_fmt_inr(s.expected_loss)}</td><td class="num good">{_fmt_inr(s.tax_offset)}</td></tr>'
            for s in tax.loss_harvest_suggestions[:10]
        ) or '<tr><td colspan="4" class="muted">No loss-harvest candidates flagged.</td></tr>'
        warn = "".join(f"<li>{_h(w)}</li>" for w in tax.fee_vs_value_warnings)
        tax_html = f"""
    <p><strong>LTCG headroom remaining (FY):</strong> {_fmt_inr(tax.ltcg_headroom_remaining)}</p>
    <p><strong>Net post-tax delta:</strong> <span class="good">{_fmt_inr(tax.net_post_tax_delta)}</span></p>

    <h3>Gain Harvest Suggestions</h3>
    <table><tr><th>Holding</th><th class="num">Units (%)</th><th class="num">Expected Gain</th><th class="num">Tax Saved</th></tr>{gain_rows}</table>

    <h3>Loss Harvest Candidates</h3>
    <table><tr><th>Holding</th><th class="num">Units (%)</th><th class="num">Notional Loss</th><th class="num">Tax Offset</th></tr>{loss_rows}</table>

    {f'<ul>{warn}</ul>' if warn else ''}
"""
    else:
        tax_html = '<p class="muted">Tax-harvest review not run. Set risk profile then run tax_harvest in chat.</p>'

    fs = plan.computed.freedom_score
    if fs:
        pillars = [
            ("Liquidity", fs.pillars.liquidity, "Months of expense coverage in liquid assets."),
            ("Debt", fs.pillars.debt, "EMI-to-income + debt-to-asset ratio."),
            ("Investment", fs.pillars.investment, "Portfolio scale vs. income; equity fit."),
            ("Discipline", fs.pillars.discipline, "Savings rate + SIP cadence + timeline."),
            ("Risk", fs.pillars.risk, "Insurance adequacy (city-adjusted)."),
        ]
        pillar_rows = "".join(
            f'<tr><td>{name}</td>'
            f'<td class="num">{score:.0f}/100</td>'
            f'<td><div class="score-bar"><div style="width:{score}%"></div></div></td>'
            f"<td>{rationale}</td></tr>"
            for name, score, rationale in pillars
        )
        scorecard_html = f"""
    <h2>10. Freedom Score Scorecard</h2>
    <table class="scorecard">
      <tr><th>Pillar</th><th class="num">Score</th><th>Visual</th><th>Rationale</th></tr>
      {pillar_rows}
      <tr><th>Overall</th><th class="num">{fs.final_score:.1f}/100</th><th colspan="2">Required cover: life {_fmt_lakhs(fs.required_life_cover)} · medical {_fmt_lakhs(fs.required_medical_cover)}</th></tr>
    </table>
    <p><strong>Estimated freedom age:</strong> {fs.estimated_freedom_age:.1f} (target: {plan.personal_details.retirement_age_target or 60}; gap: {fs.freedom_age_gap:.1f} years)</p>
"""
    else:
        scorecard_html = '<h2>10. Freedom Score Scorecard</h2><p class="muted">Score not yet computed.</p>'

    return f"""<section class="page">
  <h2>9. Tax Harvesting</h2>
  {tax_html}

  {scorecard_html}
  {_footer(page_num)}
</section>"""


def _recommendations_disclaimer(plan: PlanState, page_num: int) -> str:
    fs = plan.computed.freedom_score
    rp = plan.computed.risk_profile
    actions: list[str] = []
    if rp and rp.goal_actions:
        actions.extend(rp.goal_actions)
    if fs and fs.freedom_age_gap and fs.freedom_age_gap > 0:
        actions.append(
            f"Close the {fs.freedom_age_gap:.1f}-year freedom gap by raising the SIP commitment ≥ ₹{int(((fs.freedom_age_gap or 1) * 5_000)):,}/mo or extending retirement target."
        )
    if not plan.insurance_details.term_plan or not (plan.insurance_details.term_plan.cover_amount or 0):
        actions.append("Buy a term cover at ≥ 10× annual income; this is the most cost-effective risk transfer.")
    if not actions:
        actions = [
            "Review plan quarterly. Re-balance allocation if drift exceeds 5pp on any bucket.",
            "Maintain 6-month emergency fund in sweep-FD; avoid using it for SIP top-up.",
            "Increase SIP by 10% every year (step-up) to keep up with inflation and salary growth.",
        ]

    actions_html = "".join(f"<li>{_h(a)}</li>" for a in actions)

    return f"""<section class="page">
  <h2>11. Actionable Strategy & 12-Month Roadmap</h2>

  <h3>Phase 1 — Stabilize (0–30 days)</h3>
  <ul>
    <li>Confirm every income/expense line in chat or by uploading bank statements.</li>
    <li>Top up the emergency fund to 6× monthly fixed expenses.</li>
    <li>Plug the insurance gap (life + medical) flagged in §4.</li>
  </ul>

  <h3>Phase 2 — Re-allocate (30–90 days)</h3>
  <ul>
    <li>Move surplus into the recommended allocation buckets (§7).</li>
    <li>Increase SIPs in line with monthly surplus ({_fmt_inr(((plan.freedom_score_inputs.monthly_income or 0) - (plan.freedom_score_inputs.monthly_expenses or 0) - (plan.freedom_score_inputs.monthly_emi or 0)) * 0.7)}/mo target).</li>
    <li>Run tax_harvest at FY-end to use the LTCG headroom (§9).</li>
  </ul>

  <h3>Phase 3 — Monitor & Compound (Quarterly)</h3>
  <ul>
    <li>Re-run the Freedom Score; pillar that drops &gt; 10 points triggers action.</li>
    <li>Review goals against the cash-flow table; reset target year/amount if life events change.</li>
    <li>Step up SIPs by 10% each year.</li>
  </ul>

  <h3>Plan-Specific Actions</h3>
  <ol>{actions_html}</ol>

  <h2>12. Disclaimer</h2>
  <p class="disclaimer">
    This document is for informational purposes only and does not constitute investment advice, an offer
    to sell, or a solicitation of an offer to buy any security. The information contained herein is based
    on the data the household provided to Stackwealth Planner; its accuracy and completeness are the
    user's responsibility. Past performance is not indicative of future results. All investments involve
    risk, including the possible loss of principal. Stackwealth Planner and its affiliates are not liable
    for any decisions made based on this report. Please consult a SEBI-registered investment advisor
    before acting on any of the recommendations above.
  </p>
  {_footer(page_num)}
</section>"""


def _build_html(plan: PlanState) -> str:
    sections = [
        _cover_page(plan),
        _executive_summary(plan, 2),
        _profile_income_expenses(plan, 3),
        _net_worth_holdings(plan, 4),
        _insurance_liabilities(plan, 5),
        _goals(plan, 6),
        _risk_allocation(plan, 7),
        _cashflow(plan, 8),
        _tax_freedom_scorecard(plan, 9),
        _recommendations_disclaimer(plan, 10),
    ]
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>Comprehensive Financial Plan — {_h(plan.personal_details.full_name or plan.household_id)}</title>
<style>{CSS}</style>
</head><body>
{''.join(sections)}
</body></html>"""


# ── Entry point ────────────────────────────────────────────────────────────


async def render_plan_pdf(household_id: str) -> dict:
    plan = await get_plan(household_id)
    if not plan:
        return {
            "ok": False,
            "html": f'<!doctype html><body style="font-family:sans-serif;padding:2rem;">'
                    f'<h1>Household {_h(household_id)} not found</h1></body>',
        }

    report_html = _build_html(plan)

    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception:
        return {"ok": False, "html": report_html}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            try:
                page = await browser.new_page()
                await page.set_content(report_html, wait_until="domcontentloaded")
                client_label = html.escape(
                    plan.personal_details.full_name or plan.household_id
                )
                footer_template = (
                    '<div style="font-size:8pt;color:#71717a;width:100%;'
                    'padding:0 14mm;display:flex;justify-content:space-between;'
                    'border-top:1px solid #e4e4e7;padding-top:2mm;">'
                    f'<span>StackWealth Planner — {client_label}</span>'
                    '<span>Page <span class="pageNumber"></span>'
                    ' / <span class="totalPages"></span></span>'
                    '</div>'
                )
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "14mm", "right": "14mm", "bottom": "20mm", "left": "14mm"},
                    display_header_footer=True,
                    header_template='<div></div>',
                    footer_template=footer_template,
                )
                return {"ok": True, "bytes": pdf_bytes}
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as e:
        return {
            "ok": False,
            "html": (
                report_html
                + f'<div style="background:#fef2f2;color:#7f1d1d;padding:8px;'
                  f'font-family:sans-serif;font-size:11px;">PDF render failed: {_h(str(e))}. '
                  f"Use browser Print → Save as PDF.</div>"
            ),
        }
