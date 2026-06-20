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
from . import cfp as cfp_skill
from . import suggestions as suggestions_skill


# ── Helpers ────────────────────────────────────────────────────────────────


def _age_from_dob(dob: str | None) -> int | None:
    """Robust DOB → current age. Accepts DD-MM-YYYY, YYYY-MM-DD, and
    slash-separated variants. Returns None if no recognisable 4-digit
    year is present. Was crashing PDF generation when the LLM emitted
    ISO format ('1990-08-12') because the previous [-4:] trick read
    '8-12' as the year and int() blew up."""
    if not dob:
        return None
    parts = str(dob).replace("/", "-").split("-")
    for p in parts:
        if p.isdigit() and len(p) == 4 and 1900 < int(p) < 2100:
            return datetime.now().year - int(p)
    return None


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
/* Stack Wealth — branded report stylesheet.
   Palette: matcha green (brand), graphite (text), warm cream (page bg),
   tinted callout surfaces for status (emerald / amber / rose).      */

:root {
  --brand:        #5f7d56;   /* matcha primary */
  --brand-soft:   #e8efe4;   /* tinted surface */
  --brand-deep:   #3a4f33;   /* deep accent for headers */
  --ink:          #18181b;   /* main text */
  --ink-soft:     #52525b;   /* secondary text */
  --ink-muted:    #a1a1aa;   /* faint */
  --line:         #e4e4e7;   /* borders */
  --line-soft:    #f4f4f5;   /* table-row tint */
  --cream:        #fbfaf7;   /* page bg */
  --good:         #15803d;
  --good-bg:      #ecfdf5;
  --warn:         #b45309;
  --warn-bg:      #fef3c7;
  --bad:          #b91c1c;
  --bad-bg:       #fef2f2;
  --info-bg:      #fffbeb;
  --info-bd:      #fde68a;
}

@page { size: A4; margin: 14mm 14mm 18mm 14mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: 'Helvetica Neue', 'Inter', Arial, sans-serif;
  color: var(--ink);
  background: var(--cream);
  font-size: 10.5pt;
  line-height: 1.5;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.page { page-break-after: always; padding-bottom: 18mm; position: relative; }
.page:last-child { page-break-after: auto; }

/* ── Headings ────────────────────────────────────────────────────────── */
h1 { font-size: 24pt; margin: 0 0 5mm; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
h2 {
  font-size: 14pt;
  margin: 9mm 0 4mm;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--brand-deep);
  padding: 2.5mm 4mm;
  background: linear-gradient(90deg, var(--brand-soft) 0%, transparent 100%);
  border-left: 3.5mm solid var(--brand);
  border-radius: 0 1.5mm 1.5mm 0;
}
h3 {
  font-size: 11.5pt;
  margin: 6mm 0 2.5mm;
  font-weight: 600;
  color: var(--brand-deep);
  border-bottom: 1px solid var(--brand-soft);
  padding-bottom: 1.2mm;
  display: inline-block;
  min-width: 60mm;
}
h4 { font-size: 10.5pt; margin: 3mm 0 1.5mm; font-weight: 600; color: var(--brand-deep); }
p  { margin: 0 0 2.5mm; }
ul, ol { margin: 0 0 3mm 5mm; padding: 0; }
li { margin: 0 0 1mm; }

/* ── Tables ──────────────────────────────────────────────────────────── */
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 9.8pt; background: white; border-radius: 1.5mm; overflow: hidden; box-shadow: 0 1px 0 var(--line); }
th, td { padding: 2.2mm 3mm; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
tr:last-child th, tr:last-child td { border-bottom: none; }
thead th {
  background: var(--brand-deep);
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  font-size: 8.5pt;
  border-bottom: none;
}
tbody tr:nth-child(even) td { background: var(--line-soft); }
tbody tr.subtotal td, tbody tr.total td { background: var(--brand-soft) !important; font-weight: 600; color: var(--brand-deep); }
tbody tr.total td { border-top: 2px solid var(--brand); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
td.label-cell { font-weight: 500; color: var(--ink); }

/* ── Cover ──────────────────────────────────────────────────────────── */
.cover {
  padding-top: 0;
  position: relative;
  min-height: 250mm;
}
.cover-band {
  background: var(--brand);
  color: white;
  padding: 22mm 14mm 18mm;
  margin: -14mm -14mm 8mm -14mm;
  position: relative;
}
.cover-band::after {
  content: "";
  position: absolute;
  bottom: -3mm;
  left: 0;
  right: 0;
  height: 3mm;
  background: var(--brand-deep);
}
.cover-band .brand { font-size: 11pt; letter-spacing: 0.25em; text-transform: uppercase; opacity: 0.85; margin-bottom: 4mm; }
.cover-band h1 { color: white; font-size: 30pt; line-height: 1.05; margin: 0 0 3mm; letter-spacing: -0.02em; }
.cover-band .sub { font-size: 12pt; opacity: 0.85; }
.cover .prepared-for { text-align: center; margin: 14mm 0 8mm; }
.cover .prepared-for .label { font-size: 9.5pt; color: var(--ink-soft); letter-spacing: 0.2em; text-transform: uppercase; }
.cover .prepared-for .name { font-size: 16pt; font-weight: 600; letter-spacing: 0.04em; margin: 3mm 0 2mm; color: var(--brand-deep); }
.cover .prepared-for .meta { font-size: 10pt; color: var(--ink-soft); }
.cover .headline-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 3mm;
  margin: 8mm 0;
}
.headline-tile {
  background: white;
  border: 1px solid var(--line);
  border-top: 3px solid var(--brand);
  border-radius: 2mm;
  padding: 5mm 4mm;
  text-align: center;
}
.headline-tile .lbl { font-size: 8.5pt; color: var(--ink-soft); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 2mm; }
.headline-tile .val { font-size: 15pt; font-weight: 700; color: var(--brand-deep); letter-spacing: -0.01em; }
.headline-tile .note { font-size: 9pt; color: var(--ink-soft); margin-top: 1mm; }
.cover-foot { font-size: 9.5pt; line-height: 1.55; color: var(--ink-soft); margin-top: 8mm; padding: 4mm 5mm; background: var(--brand-soft); border-radius: 1.5mm; }

/* ── Headline / Callout boxes ──────────────────────────────────────── */
.headline-bar {
  background: var(--brand-soft);
  padding: 4mm 5mm;
  border-left: 4px solid var(--brand);
  margin: 3mm 0 5mm;
  border-radius: 0 1.5mm 1.5mm 0;
}
.headline-bar h1 { font-size: 18pt; color: var(--brand-deep); }

.callout {
  margin: 4mm 0;
  padding: 3.5mm 5mm;
  border-radius: 1.5mm;
  border-left: 3.5mm solid;
}
.callout.good   { background: var(--good-bg); border-color: var(--good); color: #064e3b; }
.callout.warn   { background: var(--warn-bg); border-color: var(--warn); color: #78350f; }
.callout.bad    { background: var(--bad-bg);  border-color: var(--bad);  color: #7f1d1d; }
.callout.info   { background: var(--info-bg); border-color: var(--info-bd); color: #713f12; }
.callout strong { display: block; font-size: 10.5pt; margin-bottom: 1mm; }
.callout p { margin: 0; font-size: 10pt; }

/* ── Status badges / pills ─────────────────────────────────────────── */
.badge {
  display: inline-block;
  padding: 0.8mm 2.5mm;
  border-radius: 8mm;
  font-size: 8.5pt;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.badge.good { background: var(--good-bg); color: var(--good); border: 1px solid #a7f3d0; }
.badge.warn { background: var(--warn-bg); color: var(--warn); border: 1px solid #fde68a; }
.badge.bad  { background: var(--bad-bg);  color: var(--bad);  border: 1px solid #fecaca; }
.badge.neutral { background: var(--line-soft); color: var(--ink-soft); border: 1px solid var(--line); }

.pill {
  display: inline-block;
  padding: 0.5mm 2mm;
  border-radius: 1.5mm;
  background: var(--brand-soft);
  color: var(--brand-deep);
  font-size: 9pt;
  font-weight: 500;
}

/* ── Stat cards ─────────────────────────────────────────────────────── */
.kbox { display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; margin: 3mm 0; }
.kbox-3 { grid-template-columns: 1fr 1fr 1fr; }
.kbox-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
.kcell {
  background: white;
  padding: 4mm 5mm;
  border: 1px solid var(--line);
  border-top: 2.5px solid var(--brand);
  border-radius: 1.5mm;
}
.kcell .label {
  font-size: 8.5pt;
  color: var(--ink-soft);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 1.5mm;
  font-weight: 600;
}
.kcell .val { font-size: 14pt; font-weight: 700; color: var(--brand-deep); letter-spacing: -0.01em; }
.kcell .note { font-size: 9pt; color: var(--ink-soft); margin-top: 1.5mm; line-height: 1.4; }

/* ── Muted / secondary text ─────────────────────────────────────────── */
.muted { color: var(--ink-soft); font-size: 9.5pt; }
.tiny  { font-size: 9pt; color: var(--ink-muted); }

/* ── Status text ────────────────────────────────────────────────────── */
.bad  { color: var(--bad); font-weight: 600; }
.good { color: var(--good); font-weight: 600; }
.warn { color: var(--warn); font-weight: 600; }

/* ── Score / progress bar ──────────────────────────────────────────── */
.score-bar { height: 4mm; background: var(--line); border-radius: 2mm; overflow: hidden; }
.score-bar > div { height: 100%; background: var(--brand); border-radius: 2mm; }

/* ── Section opener strip ──────────────────────────────────────────── */
.section-tag {
  display: inline-block;
  background: var(--brand);
  color: white;
  font-size: 9pt;
  font-weight: 600;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  padding: 1mm 3mm;
  border-radius: 1mm;
  margin-bottom: 2mm;
}

/* ── End marker ────────────────────────────────────────────────────── */
.end-marker {
  text-align: center;
  margin-top: 10mm;
  padding: 5mm 0;
  border-top: 1px solid var(--brand-soft);
  color: var(--brand-deep);
  font-size: 9.5pt;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
"""


def _footer(_page_num: int) -> str:
    """No-op — kept so call sites compile. Real footer is injected per printed
    page via Playwright's footer_template."""
    return ""


def _cover_page(plan: PlanState) -> str:
    """Page 1: Brand strip + headline scoreboard. No empty whitespace —
    the user wants the first three pages to be a dense self-contained
    summary of the entire plan."""
    pd = plan.personal_details
    fsi = plan.freedom_score_inputs
    nw = plan.computed.net_worth
    fs = plan.computed.freedom_score
    rp = plan.computed.risk_profile
    al = plan.computed.allocation
    headline = plan.computed.headline_amount_at_horizon
    horizon = plan.computed.horizon_years
    name = pd.full_name or plan.household_id
    today = datetime.now().strftime("%B %d, %Y")

    monthly_income = fsi.monthly_income or 0
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0
    surplus = monthly_income - monthly_expenses - monthly_emi
    surplus_rate = (surplus / monthly_income * 100) if monthly_income else 0

    fs_val = f"{fs.final_score:.0f}/100" if fs else "—"
    fs_age = f"Estimated freedom age {fs.estimated_freedom_age:.0f}" if fs else "Run freedom_score to populate"
    rp_val = f"{rp.recommended_score:.0f} · {rp.recommended_profile}" if rp else "—"
    rp_note = (
        f"Capacity {rp.capacity_score:.0f} · Need {rp.need_score:.0f} · Willingness {rp.willingness_score:.0f}"
        if rp
        else "Risk profile not set"
    )
    if al:
        rec = al.recommended_allocation
        al_val = f"{rec.equity:.0f}/{rec.debt:.0f}/{rec.gold:.0f}/{rec.cash:.0f}"
        al_note = f"Equity / Debt / Gold / Cash · {al.tactical_regime_label}"
    else:
        al_val = "—"
        al_note = "Allocation not yet computed"

    return f"""<section class="page cover">
  <div class="brand">Stackwealth Research Desk</div>
  <h1>Comprehensive Financial Plan</h1>
  <div class="sub">Institutional-Grade Household Review</div>
  <div class="cover-meta">
    <span><strong>Client:</strong> {_h(name)}</span>
    <span><strong>Date:</strong> {today}</span>
    <span><strong>Household ID:</strong> {_h(plan.household_id)}</span>
  </div>

  <h3 class="cover-section">Plan Scoreboard</h3>
  <div class="kbox kbox-3">
    <div class="kcell"><div class="label">Net Worth Today</div><div class="val">{_fmt_lakhs(nw.total)}</div><div class="note">Liquid {_fmt_lakhs(nw.liquid)} · Debts {_fmt_lakhs(nw.debts_total)}</div></div>
    <div class="kcell"><div class="label">Monthly Surplus</div><div class="val">{_fmt_inr(surplus)}</div><div class="note">{_fmt_pct(surplus_rate)} savings rate · Income {_fmt_inr(monthly_income)}</div></div>
    <div class="kcell"><div class="label">{horizon}-Year Projection</div><div class="val">{_fmt_lakhs(headline)}</div><div class="note">At age {(fsi.age or 30) + horizon}, current trajectory</div></div>
    <div class="kcell"><div class="label">Freedom Score</div><div class="val">{_h(fs_val)}</div><div class="note">{_h(fs_age)}</div></div>
    <div class="kcell"><div class="label">Risk Profile</div><div class="val">{_h(rp_val)}</div><div class="note">{_h(rp_note)}</div></div>
    <div class="kcell"><div class="label">Recommended Allocation</div><div class="val">{_h(al_val)}</div><div class="note">{_h(al_note)}</div></div>
  </div>

  <p class="muted cover-foot">This report begins with a three-page executive summary covering the household snapshot, allocation, goals, Monte Carlo outlook, and prioritized actions. Subsequent pages drill into income/expenses, holdings, liabilities, insurance, goals, risk profile, allocation, cashflow, tax, and the Freedom scorecard. Every figure is sourced from the canonical PlanState — nothing is inferred without an underlying input.</p>
  {_footer(1)}
</section>"""


def _executive_summary(plan: PlanState, page_num: int) -> str:
    """Page 2: Plan Summary — household snapshot, full income/expense table,
    goals with success probabilities, recommended allocation, insurance gaps."""
    pd = plan.personal_details
    fsi = plan.freedom_score_inputs
    fs = plan.computed.freedom_score
    al = plan.computed.allocation
    mc = plan.computed.monte_carlo
    monthly_income = fsi.monthly_income or 0
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0
    surplus = monthly_income - monthly_expenses - monthly_emi
    age = fsi.age or "—"

    # Goals + per-goal success probabilities (from MC if present).
    prob_by_id = {}
    if mc and mc.goal_success_probabilities:
        prob_by_id = {g.goal_id: g.probability for g in mc.goal_success_probabilities}

    if plan.financial_goals:
        goal_rows = "".join(
            f'<tr><td>{_h(g.goal_name)}</td>'
            f'<td>{_h((g.kind or "").replace("_", " ").title())}</td>'
            f'<td class="num">{_h(g.target_year or "—")}</td>'
            f'<td class="num">{_fmt_lakhs(g.target_amount or 0)}</td>'
            f'<td>{_h((g.priority or "").title())}</td>'
            f'<td class="num">{_fmt_pct(prob_by_id.get(g.id, 0) * 100, 0) if g.id in prob_by_id else "—"}</td></tr>'
            for g in plan.financial_goals
        )
    else:
        goal_rows = '<tr><td colspan="6" class="muted">No goals captured.</td></tr>'

    # Allocation breakdown — strategic + recommended side by side.
    if al:
        strat = al.strategic_allocation
        rec = al.recommended_allocation
        eq_split = al.recommended_equity_split
        alloc_html = f"""
        <table>
          <tr><th>Bucket</th><th class="num">Strategic</th><th class="num">Recommended</th><th>Notes</th></tr>
          <tr><td>Equity</td><td class="num">{strat.equity:.0f}%</td><td class="num">{rec.equity:.0f}%</td><td>Large {eq_split.large:.0f}% · Mid {eq_split.mid:.0f}% · Small {eq_split.small:.0f}%</td></tr>
          <tr><td>Debt</td><td class="num">{strat.debt:.0f}%</td><td class="num">{rec.debt:.0f}%</td><td>Duration: {_h(al.debt_duration_stance)}</td></tr>
          <tr><td>Gold</td><td class="num">{strat.gold:.0f}%</td><td class="num">{rec.gold:.0f}%</td><td>Inflation hedge</td></tr>
          <tr><td>Cash</td><td class="num">{strat.cash:.0f}%</td><td class="num">{rec.cash:.0f}%</td><td>Liquidity buffer</td></tr>
        </table>
        <p class="muted">Tactical regime: <strong>{_h(al.tactical_regime_label)}</strong> (signal score {al.tactical_regime_score:+.1f}).</p>
        """
    else:
        alloc_html = '<p class="muted">Allocation not yet computed. Run the 3-question risk profile first; allocation auto-computes alongside.</p>'

    # Insurance gap callouts.
    insurance_lines: list[str] = []
    if fs:
        ins = plan.insurance_details
        life_have = (ins.term_plan and ins.term_plan.cover_amount) or 0
        med_have = (ins.health_insurance and ins.health_insurance.cover_amount) or 0
        life_gap = max(0, fs.required_life_cover - life_have)
        med_gap = max(0, fs.required_medical_cover - med_have)
        if life_gap > 0:
            insurance_lines.append(
                f'<li><span class="bad">Life cover gap:</span> required {_fmt_lakhs(fs.required_life_cover)}, current {_fmt_lakhs(life_have)} — '
                f'{_fmt_lakhs(life_gap)} short. Top up term plan.</li>'
            )
        if med_gap > 0:
            insurance_lines.append(
                f'<li><span class="bad">Medical cover gap:</span> required {_fmt_lakhs(fs.required_medical_cover)}, current {_fmt_lakhs(med_have)} — '
                f'{_fmt_lakhs(med_gap)} short. Add family floater.</li>'
            )
        if not insurance_lines:
            insurance_lines.append('<li><span class="good">Insurance adequately covered against city-adjusted requirements.</span></li>')
    insurance_html = f'<ul>{"".join(insurance_lines)}</ul>' if insurance_lines else '<p class="muted">Run freedom_score to compute insurance requirements.</p>'

    return f"""<section class="page">
  <div class="headline"><h1>1. Plan Summary</h1></div>
  <p>Comprehensive snapshot of <strong>{_h(pd.full_name or plan.household_id)}'s</strong> household plan as of {datetime.now().strftime('%B %d, %Y')}.
  Age {_h(age)} · {_h(pd.city_of_residence or '—')} ({_h(pd.city_type or '—')}) · {_h(pd.marital_status or 'status unknown')} · {_h(pd.dependents or 0)} dependents · retirement target {_h(pd.retirement_age_target or 60)}.</p>

  <h3>Cashflow Position (Monthly)</h3>
  <table>
    <tr><th>Stream</th><th class="num">Amount</th><th>Share of Income</th></tr>
    <tr><td>Take-home (all sources)</td><td class="num">{_fmt_inr(monthly_income)}</td><td>—</td></tr>
    <tr><td>Fixed expenses</td><td class="num">{_fmt_inr(monthly_expenses)}</td><td>{_fmt_pct((monthly_expenses / monthly_income * 100) if monthly_income else 0)}</td></tr>
    <tr><td>EMI burden</td><td class="num">{_fmt_inr(monthly_emi)}</td><td>{_fmt_pct((monthly_emi / monthly_income * 100) if monthly_income else 0)}</td></tr>
    <tr><td><strong>Surplus available for SIP / goals</strong></td><td class="num"><strong>{_fmt_inr(surplus)}</strong></td><td><strong>{_fmt_pct((surplus / monthly_income * 100) if monthly_income else 0)}</strong></td></tr>
  </table>

  <h3>Goals at a Glance</h3>
  <table>
    <tr><th>Goal</th><th>Kind</th><th class="num">Year</th><th class="num">Target</th><th>Priority</th><th class="num">Success Prob.</th></tr>
    {goal_rows}
  </table>
  <p class="muted">Success probability is the fraction of {mc.paths_count if mc else 0} Monte Carlo paths that meet the inflation-adjusted target by the goal's horizon. Run montecarlo_run to populate.</p>

  <h3>Recommended Allocation</h3>
  {alloc_html}

  <h3>Insurance Gaps</h3>
  {insurance_html}
  {_footer(page_num)}
</section>"""


def _outlook_actions(plan: PlanState, page_num: int) -> str:
    """Page 3: Outlook + Top Actions — Monte Carlo, key cashflow milestones,
    prioritized recommendations, critical flags."""
    fsi = plan.freedom_score_inputs
    mc = plan.computed.monte_carlo
    rp = plan.computed.risk_profile
    fs = plan.computed.freedom_score
    cf = plan.computed.cashflow
    headline = plan.computed.headline_amount_at_horizon
    horizon = plan.computed.horizon_years
    age = fsi.age or 30
    retirement_age = plan.personal_details.retirement_age_target or 60

    # Monte Carlo block
    if mc:
        mc_html = f"""
        <table>
          <tr><th>Percentile</th><th class="num">Freedom Age</th><th>Reading</th></tr>
          <tr><td>P10 (lucky)</td><td class="num">{mc.p10_freedom_age:.0f}</td><td>10% of paths reach 25× expenses by this age or earlier</td></tr>
          <tr><td>P50 (median)</td><td class="num">{mc.p50_freedom_age:.0f}</td><td>Half of paths reach financial freedom by this age</td></tr>
          <tr><td>P90 (unlucky)</td><td class="num">{mc.p90_freedom_age:.0f}</td><td>90% of paths reach freedom by this age</td></tr>
        </table>
        <p class="muted">Monte Carlo simulation across {mc.paths_count} paths using the recommended allocation's blended return and equity-driven volatility.</p>
        """
    else:
        mc_html = '<p class="muted">Monte Carlo not yet run. Use montecarlo_run after risk_assess to populate.</p>'

    # Cashflow milestones
    milestones_html = '<p class="muted">Cashflow projection not yet computed.</p>'
    if cf and cf.rows:
        def _row_at_age(target_age: int):
            for r in cf.rows:
                if r.age >= target_age:
                    return r
            return cf.rows[-1] if cf.rows else None
        ages = [age, age + 5, age + 15, retirement_age, age + horizon]
        seen = set()
        rows_html = []
        for a in ages:
            r = _row_at_age(a)
            if not r or r.year in seen:
                continue
            seen.add(r.year)
            label = f"Age {r.age}"
            if r.age == retirement_age:
                label += " (retirement)"
            rows_html.append(
                f'<tr><td>{label}</td><td class="num">{r.year}</td>'
                f'<td class="num">{_fmt_lakhs(r.income)}</td>'
                f'<td class="num">{_fmt_lakhs(r.expenses)}</td>'
                f'<td class="num">{_fmt_lakhs(r.total_net_worth)}</td></tr>'
            )
        milestones_html = f"""
        <table>
          <tr><th>Milestone</th><th class="num">Year</th><th class="num">Annual Income</th><th class="num">Annual Expenses</th><th class="num">Net Worth</th></tr>
          {''.join(rows_html)}
        </table>
        """

    # Top Actions — keyed off pillar gaps + risk alignment.
    actions: list[str] = []
    if rp:
        if rp.alignment_status == "goal_risk_mismatch":
            actions.append(
                f'<li class="bad"><strong>Goal-risk mismatch.</strong> Goals demand more risk than is prudent. '
                f'Pick one: increase periodic contribution, extend horizon, reduce target, or split into essential + aspirational.</li>'
            )
        if "Emergency fund covers less than 3 months" in (rp.key_warnings or []):
            actions.append(
                '<li class="warn"><strong>Build emergency fund.</strong> Park 6 months of expenses in a high-yield savings or sweep-FD before adding portfolio risk.</li>'
            )
    if fs:
        ranked = sorted(
            [
                ("Liquidity", fs.pillars.liquidity, "Build emergency fund equal to 6 months of expenses; park in high-yield savings or sweep-FD."),
                ("Debt", fs.pillars.debt, "Reduce EMI exposure below 35% of monthly income; prepay highest-interest loans first."),
                ("Investment", fs.pillars.investment, "Ramp up SIP to align portfolio with annual income × 5; tilt to equity per recommended allocation."),
                ("Discipline", fs.pillars.discipline, "Automate SIPs and lock in savings rate ≥ 30%; review every quarter against the cash-flow plan."),
                ("Risk", fs.pillars.risk, "Top up term cover to 10× annual income (city-adjusted); ensure family floater covers all dependents."),
            ],
            key=lambda x: x[1],
        )
        for name, score, action in ranked[:3]:
            actions.append(f'<li><strong>{name} pillar at {score:.0f}/100:</strong> {action}</li>')
    if not actions:
        actions.append("<li>Plan is in good shape — continue reviewing quarterly.</li>")
    actions_html = f'<ol>{"".join(actions)}</ol>'

    # Critical flags strip
    flags: list[str] = []
    if rp and rp.alignment_status == "goal_risk_mismatch":
        flags.append('<li class="bad">Goal-risk mismatch active</li>')
    if fs and fs.pillars.investment < 30:
        flags.append('<li class="warn">Investment pillar critically low (no/low SIP)</li>')
    if fs and fs.pillars.risk < 50:
        flags.append('<li class="warn">Underinsured for city × dependent profile</li>')
    if fs and fs.pillars.liquidity < 50:
        flags.append('<li class="warn">Emergency fund below 3 months of expenses</li>')
    if not flags:
        flags.append('<li class="good">No critical flags.</li>')
    flags_html = f'<ul>{"".join(flags)}</ul>'

    return f"""<section class="page">
  <div class="headline"><h1>2. Outlook &amp; Top Actions</h1></div>

  <h3>Monte Carlo Outlook (Freedom Age)</h3>
  {mc_html}

  <h3>Projection Milestones</h3>
  {milestones_html}
  <p class="muted">{horizon}-year projection lands at <strong>{_fmt_lakhs(headline)}</strong> at age {age + horizon} on the current trajectory.</p>

  <h3>Top Actions — Ranked by Impact</h3>
  {actions_html}

  <h3>Critical Flags</h3>
  {flags_html}
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
        # Pages 1-3: dense executive summary self-contained.
        _cover_page(plan),
        _executive_summary(plan, 2),
        _outlook_actions(plan, 3),
        # Pages 4+: drill-down detail.
        _profile_income_expenses(plan, 4),
        _net_worth_holdings(plan, 5),
        _insurance_liabilities(plan, 6),
        _goals(plan, 7),
        _risk_allocation(plan, 8),
        _cashflow(plan, 9),
        _tax_freedom_scorecard(plan, 10),
        _recommendations_disclaimer(plan, 11),
    ]
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>Comprehensive Financial Plan — {_h(plan.personal_details.full_name or plan.household_id)}</title>
<style>{CSS}</style>
</head><body>
{''.join(sections)}
</body></html>"""


# ── Sandeep-style builder ─────────────────────────────────────────────────
# Mirrors `Sandeep_Hongamath_Financial_Plan_v1.docx` section-by-section.
# 9 sections; same headers, same tables, same field labels. Every numeric
# cell pulls from PlanState or from the CFP engine (Excel-faithful).


def _build_sandeep_html(plan: PlanState) -> str:
    cfp = cfp_skill.compute_cfp(plan)
    # Compute the AI suggestions once and share across the net-worth overview
    # (top of report) and the Section-4B suggestions block.
    try:
        sug = suggestions_skill.compute_suggestions(plan)
    except Exception:
        sug = None
    sections = [
        _sandeep_cover(plan, cfp),
        _sandeep_networth_overview(plan, cfp, sug),
        _sandeep_s1_profile(plan),
        _sandeep_s2_cashflow(plan, cfp),
        _sandeep_s3_networth(plan),
        _sandeep_s4_goals(plan, cfp),
        _sandeep_s4b_suggestions(plan, sug),
        _sandeep_s5_strategy(plan, cfp),
        _sandeep_s6_risk(plan, cfp),
        _sandeep_s7_tax(plan),
        _sandeep_s8_future(plan, cfp),
        _sandeep_s9_roadmap(plan, cfp),
    ]
    name = plan.personal_details.full_name or plan.household_id
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>Comprehensive Financial Plan — {_h(name)}</title>
<style>{CSS}</style>
</head><body>
{''.join(sections)}
</body></html>"""


def _sandeep_cover(plan: PlanState, cfp: cfp_skill.CFPOutput) -> str:
    pd = plan.personal_details
    fsi = plan.freedom_score_inputs
    nw = plan.computed.net_worth
    persons = plan.assumptions.persons
    name = pd.full_name or plan.household_id
    spouse = persons[1].name if len(persons) > 1 and persons[1].name else None
    headline = f"MR. {name.upper()}" + (f" & MRS. {spouse.upper()}" if spouse else "")
    today = datetime.now().strftime("%B %Y")
    city = pd.city_of_residence or ""
    retire_year = (datetime.now().year + max(0, (pd.retirement_age_target or 60) - (fsi.age or 30)))

    monthly_income = fsi.monthly_income or 0
    monthly_expenses = fsi.monthly_expenses or 0
    monthly_emi = fsi.monthly_emi or 0
    surplus_gross = monthly_income - monthly_expenses - monthly_emi
    return f"""<section class="page cover">
  <div class="cover-band">
    <p class="brand">Stack Wealth — Research Desk</p>
    <h1>Comprehensive<br/>Financial Plan</h1>
    <p class="sub">A Forward-Looking Wealth &amp; Life Planning Report</p>
  </div>

  <div class="prepared-for">
    <div class="label">Prepared For</div>
    <div class="name">{_h(headline)}</div>
    <div class="meta">{_h(city)}  ·  {_h(today)}</div>
  </div>

  <div class="headline-grid">
    <div class="headline-tile">
      <div class="lbl">Monthly Income</div>
      <div class="val">{_fmt_inr(monthly_income)}</div>
      <div class="note">Net, after taxes</div>
    </div>
    <div class="headline-tile">
      <div class="lbl">Monthly Surplus</div>
      <div class="val">{_fmt_inr(surplus_gross)}</div>
      <div class="note">Pre-investments</div>
    </div>
    <div class="headline-tile">
      <div class="lbl">Net Worth</div>
      <div class="val">{_fmt_lakhs(nw.total)}</div>
      <div class="note">Today's snapshot</div>
    </div>
    <div class="headline-tile">
      <div class="lbl">Retirement Target</div>
      <div class="val">Age {pd.retirement_age_target or 60}</div>
      <div class="note">Year {retire_year}</div>
    </div>
  </div>

  <div class="cover-foot">
    <strong style="color:var(--brand-deep);">What's inside.</strong>
    Client Profiling · Cash Flow Analysis · Net Worth Assessment ·
    Goal-Based Planning · Investment Strategy · Risk Management ·
    Tax Efficiency · Future-Proofing &amp; Scenario Analysis · Execution Roadmap.
    Every number on this report traces back to PlanState data and the firm's CFP Excel methodology.
  </div>
</section>"""


def _sandeep_networth_overview(plan: PlanState, cfp: cfp_skill.CFPOutput, sug: dict | None) -> str:
    """Up-front net-worth trajectory — the headline of the whole plan. Shows
    the baseline (current-plan) net worth over the full horizon AND, when the
    AI suggests improvements, the suggested-plan trajectory side-by-side."""
    baseline = [{"year": p.year, "value": p.value} for p in (plan.computed.net_worth_series or [])]
    if not baseline:
        return ""
    fsi = plan.freedom_score_inputs
    start_age = fsi.age or (cfp.summary.get("current_age") if cfp.summary else None) or 30
    start_year = baseline[0]["year"]
    horizon_years = baseline[-1]["year"] - start_year

    ret = cfp.retirement or {}
    retire_year = start_year + round(ret.get("years_to_retire", 0) or 0)

    sug_series = []
    sug_has_gaps = bool(sug and sug.get("has_gaps"))
    if sug_has_gaps:
        sug_series = (sug.get("suggested") or {}).get("net_worth_series") or []
    sug_by_year = {p.get("year"): p.get("value") for p in sug_series}

    def _at(series, year):
        m = next((p for p in series if p.get("year") == year), None)
        return (m or {}).get("value", 0) if m else 0

    current_nw = plan.computed.net_worth.total if plan.computed.net_worth else 0
    base_at_retire = _at(baseline, retire_year)
    base_at_horizon = baseline[-1]["value"]
    sug_at_retire = sug_by_year.get(retire_year)
    sug_at_horizon = sug_series[-1].get("value") if sug_series else None

    # Headline stat cards.
    cards = f"""
    <div class="kpis">
      <div class="kcell"><div class="label">Net Worth Today</div><div class="val">{_fmt_lakhs(current_nw)}</div></div>
      <div class="kcell"><div class="label">At Retirement ({retire_year})</div><div class="val">{_fmt_lakhs(base_at_retire)}</div><div class="note">current plan</div></div>
      <div class="kcell"><div class="label">At Age {int(start_age) + horizon_years} ({baseline[-1]["year"]})</div><div class="val">{_fmt_lakhs(base_at_horizon)}</div><div class="note">current plan, {horizon_years}-yr horizon</div></div>
    </div>"""

    desc = f"""
    <p>This is the household's projected <strong>net worth over the next {horizon_years} years</strong> on the
    <strong>current plan</strong> — income growing at its post-tax rate, expenses at inflation, surplus reinvested,
    and every asset compounding at its own post-tax return. It is the single most important picture in this plan:
    where today's decisions land the family by retirement ({retire_year}) and beyond.</p>"""
    if sug_has_gaps:
        delta_h = (sug_at_horizon or base_at_horizon) - base_at_horizon
        desc += f"""
    <p>The <strong>suggested plan</strong> overlays the AI optimisation (Section 4B) — redirecting surplus, a 10%/yr
    SIP step-up, a realistic income lift, and other levers. It lifts net worth at age {int(start_age) + horizon_years}
    to <strong>{_fmt_lakhs(sug_at_horizon or base_at_horizon)}</strong>
    (<strong>{'+' if delta_h >= 0 else ''}{_fmt_lakhs(delta_h)}</strong> vs the current plan), and at retirement to
    <strong>{_fmt_lakhs(sug_at_retire or base_at_retire)}</strong>.</p>"""

    # Trajectory table (both series).
    show_sug = sug_has_gaps and bool(sug_series)
    hdr_sug = '<th class="num">Suggested Plan</th>' if show_sug else ""
    body = ""
    for p in baseline:
        yr = p["year"]
        age = int(start_age) + (yr - start_year)
        sug_cell = f'<td class="num">{_fmt_lakhs(sug_by_year.get(yr))}</td>' if show_sug else ""
        mark = ' style="font-weight:600;background:#f4f4f5;"' if yr == retire_year else ""
        body += f'<tr{mark}><td>{yr}{" · retires" if yr == retire_year else ""}</td><td class="num">{age}</td><td class="num">{_fmt_lakhs(p["value"])}</td>{sug_cell}</tr>'

    return f"""<section class="page">
  <h2>NET WORTH TRAJECTORY — {horizon_years}-YEAR OUTLOOK</h2>
  {desc}
  {cards}
  <h3>Year-by-Year Net Worth{' — Current vs Suggested' if show_sug else ''}</h3>
  <table style="font-size:8px;">
    <thead><tr><th>Year</th><th class="num">Age</th><th class="num">Current Plan</th>{hdr_sug}</tr></thead>
    <tbody>{body}</tbody>
  </table>
  <p class="muted">Values in lakhs. The current-plan series is the canonical projection used throughout this report; the suggested series reflects the recommended combined plan in Section 4B.</p>
</section>"""


def _sandeep_s1_profile(plan: PlanState) -> str:
    """SECTION 1 — Client Profiling."""
    pd = plan.personal_details
    persons = plan.assumptions.persons
    fsi = plan.freedom_score_inputs
    risk = plan.computed.risk_profile

    p1 = persons[0] if persons else None
    p2 = persons[1] if len(persons) > 1 else None
    fsname_p1 = p1.name if p1 else (pd.full_name or "—")
    fsname_p2 = p2.name if p2 else "—"
    p1_age = (_age_from_dob(p1.date_of_birth) if p1 else None) or (fsi.age or "—")
    p2_age = (_age_from_dob(p2.date_of_birth) if p2 else None) or "—"
    retire_year = (datetime.now().year + max(0, (pd.retirement_age_target or 60) - (fsi.age or 30)))
    years_to_retire = max(0, (pd.retirement_age_target or 60) - (fsi.age or 30))

    children_descr = []
    for person in persons[2:]:
        age = _age_from_dob(person.date_of_birth)
        a = str(age) if age is not None else "—"
        children_descr.append(f"{person.name} (Age {a})")
    children_cell = " & ".join(children_descr) if children_descr else (
        f"{pd.number_of_children} children" if pd.number_of_children else "None"
    )

    profile_table = f"""
    <table>
      <thead><tr><th>Parameter</th><th>Client</th><th>Spouse</th></tr></thead>
      <tbody>
        <tr><td>Full Name</td><td>{_h(fsname_p1)}</td><td>{_h(fsname_p2)}</td></tr>
        <tr><td>Date of Birth</td><td>{_h((p1 and p1.date_of_birth) or '—')}</td><td>{_h((p2 and p2.date_of_birth) or '—')}</td></tr>
        <tr><td>Current Age</td><td>{p1_age} years</td><td>{p2_age} years</td></tr>
        <tr><td>Occupation</td><td>{_h(pd.occupation or '—')}</td><td>—</td></tr>
        <tr><td>City</td><td>{_h(pd.city_of_residence or '—')}</td><td>{_h(pd.city_of_residence or '—')}</td></tr>
        <tr><td>Marital Status</td><td>{_h(pd.marital_status or '—')}</td><td>{_h(pd.marital_status or '—')}</td></tr>
        <tr><td>Children</td><td>{_h(children_cell)}</td><td>{_h(children_cell)}</td></tr>
        <tr><td>Dependents</td><td>{_h(pd.dependents or '—')}</td><td>{_h(pd.dependents or '—')}</td></tr>
        <tr><td>Retirement Age Target</td><td>{pd.retirement_age_target or 60} years (Year {retire_year})</td><td>{pd.retirement_age_target or 60} years (Year {retire_year})</td></tr>
        <tr><td>Years to Retirement</td><td>{years_to_retire} years</td><td>{years_to_retire} years</td></tr>
      </tbody>
    </table>"""

    age = fsi.age or 30
    if age < 30:
        stage = "Early-Career Accumulation"
        stage_text = "You are in the earliest, highest-leverage phase of compounding. Habits formed here — automated SIPs, term insurance, an emergency fund — pay decades of dividends."
    elif age < 45:
        stage = "Peak Accumulation Phase"
        stage_text = f"At {age}, with {years_to_retire} years to a retirement target of {pd.retirement_age_target or 60}, every investment decision carries high urgency. This phase is characterised by maximum income, multiple competing financial goals, and a need for disciplined, goal-linked investing."
    elif age < 55:
        stage = "Pre-Retirement Consolidation"
        stage_text = "Focus shifts from accumulation to consolidation — de-risking goal corpora as they approach, paying down high-interest debt, locking in insurance, and stress-testing the retirement plan."
    else:
        stage = "Retirement Transition"
        stage_text = "The corpus is now load-bearing. Withdrawal strategy, sequence-of-returns risk, and healthcare cover dominate."
    life_stage_html = f"<p>{_h(fsname_p1)} is in the <strong>{_h(stage)}</strong> — {_h(stage_text)}</p>"

    if risk:
        rp_summary = risk.recommended_profile
        rp_rows = f"""
        <tr><td>Financial Risk Capacity</td><td>{risk.capacity_score:.0f} / 100 — {_h(risk.capacity_profile)}</td><td>Binding cap: {_h((risk.capacity_binding_cap or '').replace('_', ' '))}</td></tr>
        <tr><td>Behavioural Risk Tolerance</td><td>{risk.willingness_score:.0f} / 100 — {_h(risk.willingness_profile)}</td><td>Raw willingness {risk.willingness_raw_score:.0f}</td></tr>
        <tr><td>Goal-Based Risk</td><td>{risk.need_score:.0f} / 100 — {_h(risk.need_profile)}</td><td>{_h(risk.need_primary_goal or 'No driver goal yet')}</td></tr>
        <tr><td>Overall Profile</td><td><strong>{_h(rp_summary)}</strong></td><td>Recommended score {risk.recommended_score:.0f}, prudent ceiling {risk.prudent_ceiling:.0f}</td></tr>
        """
    else:
        rp_rows = '<tr><td colspan="3" class="muted">Risk profile not yet computed — answer 3 questions in chat to populate.</td></tr>'

    return f"""<section class="page">
  <h2>SECTION 1 — CLIENT PROFILING</h2>
  <h3>1.1  Personal & Professional Overview</h3>
  {profile_table}

  <h3>1.2  Life Stage Classification</h3>
  {life_stage_html}

  <h3>1.3  Risk Assessment</h3>
  <table>
    <thead><tr><th>Risk Dimension</th><th>Assessment</th><th>Implication</th></tr></thead>
    <tbody>{rp_rows}</tbody>
  </table>
</section>"""


def _yoy_cashflow_tables(cfp: cfp_skill.CFPOutput) -> str:
    """The full year-by-year cash-flow projection — same data the canvas
    Cashflow tab renders. Two compact tables: income→surplus, and the
    financial / non-financial asset build-up to net worth."""
    rows = cfp.yoy_cashflow or []
    if not rows:
        return '<p class="muted">Year-by-year projection not available.</p>'

    def _c(v) -> str:
        return _fmt_inr(v or 0)

    income_rows = "".join(
        f'<tr><td>{r["year"]}</td><td class="num">{r["age"]}</td>'
        f'<td class="num">{_c(r.get("income_employment"))}</td>'
        f'<td class="num">{_c(r.get("income_business"))}</td>'
        f'<td class="num">{_c(r.get("income_rental"))}</td>'
        f'<td class="num">{_c(r.get("income_other"))}</td>'
        f'<td class="num">{_c(r.get("total_income"))}</td>'
        f'<td class="num">{_c(r.get("expenses"))}</td>'
        f'<td class="num">{_c(r.get("loan_repayment"))}</td>'
        f'<td class="num">{_c(r.get("surplus"))}</td></tr>'
        for r in rows
    )
    asset_rows = "".join(
        f'<tr><td>{r["year"]}</td><td class="num">{r["age"]}</td>'
        f'<td class="num">{_c(r.get("fa_opening"))}</td>'
        f'<td class="num">{_c(r.get("net_annual_cash_savings"))}</td>'
        f'<td class="num">{_c(r.get("major_withdrawals"))}</td>'
        f'<td class="num">{_c(r.get("investment_returns"))}</td>'
        f'<td class="num">{_c(r.get("lumpsum_deposit_withdrawal"))}</td>'
        f'<td class="num">{_c(r.get("financial_assets_closing"))}</td>'
        f'<td class="num">{_c(r.get("non_financial_assets_closing"))}</td>'
        f'<td class="num"><strong>{_c(r.get("net_worth"))}</strong></td></tr>'
        for r in rows
    )
    return f"""
  <h3>2.4  Year-by-Year Cash Flow Projection</h3>
  <p class="muted">Mirrors the firm's <code>YoY Cash Flow</code> tab — each income line grown at its own
  post-tax rate, expenses at inflation, surplus reinvested, and assets compounded at their post-tax returns.</p>
  <p class="muted" style="margin-top:1.5mm;"><strong>2.4a  Income, Expenses &amp; Surplus</strong></p>
  <table style="font-size:7.5px;">
    <thead><tr><th>Year</th><th class="num">Age</th><th class="num">Employment</th><th class="num">Business</th><th class="num">Rental</th><th class="num">Other</th><th class="num">Total Income</th><th class="num">Expenses</th><th class="num">Loan</th><th class="num">Surplus</th></tr></thead>
    <tbody>{income_rows}</tbody>
  </table>
  <p class="muted" style="margin-top:2mm;"><strong>2.4b  Asset Build-up &amp; Net Worth</strong></p>
  <table style="font-size:7.5px;">
    <thead><tr><th>Year</th><th class="num">Age</th><th class="num">FA Open</th><th class="num">Net Savings</th><th class="num">Withdrawals</th><th class="num">Inv. Returns</th><th class="num">Lumpsum</th><th class="num">FA Close</th><th class="num">Non-Fin. Assets</th><th class="num">Net Worth</th></tr></thead>
    <tbody>{asset_rows}</tbody>
  </table>"""


def _sandeep_s2_cashflow(plan: PlanState, cfp: cfp_skill.CFPOutput) -> str:
    """SECTION 2 — Cash Flow Analysis."""
    income = plan.income_details
    expenses = plan.monthly_expenses
    invest = plan.monthly_investments
    fsi = plan.freedom_score_inputs

    def _row(label: str, monthly: float | None, *, group_total: bool = False) -> str:
        if not monthly:
            return ""
        annual = (monthly or 0) * 12
        klass = ' style="font-weight:600;background:#f4f4f5;"' if group_total else ""
        return f'<tr{klass}><td>{_h(label)}</td><td class="num">{_fmt_inr(monthly)}</td><td class="num">{_fmt_inr(annual)}</td></tr>'

    income_rows = "".join([
        _row("Salary (In-Hand) — Client", income.client_salary_in_hand),
        _row("Salary (In-Hand) — Spouse", income.spouse_salary_in_hand),
        _row("Business Income — Client", income.client_business_income),
        _row("Business Income — Spouse", income.spouse_business_income),
        _row("Rental Income — Client", income.client_rental_income),
        _row("Rental Income — Spouse", income.spouse_rental_income),
        _row("Other Income — Client", income.client_other_income),
        _row("Other Income — Spouse", income.spouse_other_income),
    ])
    monthly_income_total = fsi.monthly_income or 0
    income_rows += _row("TOTAL INCOME", monthly_income_total, group_total=True)

    exp_rows = "".join([
        _row("Home Loan EMI / Rent", expenses.rent_or_emi),
        _row("School Fees", expenses.school_fees),
        _row("Household Expenses", expenses.household_expenses),
        _row("Groceries", expenses.groceries),
        _row("Utilities (Phone, Internet, OTT)", expenses.utilities),
        _row("Travel / Lifestyle / Dining", expenses.travel_or_lifestyle),
        _row("Medical / Healthcare", expenses.medical),
        _row("Insurance Premium", expenses.insurance_premium),
        _row("Other EMIs", expenses.other_emis),
    ])
    monthly_exp_total = fsi.monthly_expenses or 0
    monthly_emi_total = fsi.monthly_emi or 0
    exp_rows += _row("TOTAL PURE LIVING EXPENSES", monthly_exp_total + monthly_emi_total, group_total=True)

    inv_rows = "".join([
        _row("Mutual Fund SIPs", invest.mutual_fund_sip),
        _row("PPF", invest.ppf),
        _row("NPS", invest.nps),
        _row("RD", invest.rd),
        _row("Direct Equity", invest.direct_equity),
        _row("Insurance Premium (savings)", invest.insurance_premium),
        _row("Other", invest.other),
    ])
    invest_total = sum([
        invest.mutual_fund_sip or 0, invest.ppf or 0, invest.nps or 0,
        invest.rd or 0, invest.direct_equity or 0,
        invest.insurance_premium or 0, invest.other or 0,
    ])
    if invest_total > 0:
        inv_rows += _row("Investments Sub-Total", invest_total, group_total=True)

    total_outflow = monthly_exp_total + monthly_emi_total + invest_total
    gross_surplus = monthly_income_total - monthly_exp_total - monthly_emi_total
    net_surplus = monthly_income_total - total_outflow

    summary = f"""
    <tr style="font-weight:600;background:#f4f4f5;"><td>TOTAL OUTFLOW</td><td class="num">{_fmt_inr(total_outflow)}</td><td class="num">{_fmt_inr(total_outflow * 12)}</td></tr>
    <tr style="font-weight:600;"><td>GROSS SURPLUS (before investments)</td><td class="num">{_fmt_inr(gross_surplus)}</td><td class="num">{_fmt_inr(gross_surplus * 12)}</td></tr>
    <tr style="font-weight:600;"><td>NET SURPLUS (after current investments)</td><td class="num">{_fmt_inr(net_surplus)}</td><td class="num">{_fmt_inr(net_surplus * 12)}</td></tr>
    """

    gross_rate = (gross_surplus / monthly_income_total) if monthly_income_total else 0
    invest_rate = ((invest.mutual_fund_sip or 0) / monthly_income_total) if monthly_income_total else 0
    emi_rate = (monthly_emi_total / monthly_income_total) if monthly_income_total else 0

    return f"""<section class="page">
  <h2>SECTION 2 — CASH FLOW ANALYSIS</h2>
  <h3>2.1  Monthly Income vs Expenses — Detailed Breakdown</h3>
  <table>
    <thead><tr><th>Category</th><th class="num">Monthly (₹)</th><th class="num">Annual (₹)</th></tr></thead>
    <tbody>
      {income_rows}
      <tr><td colspan="3"></td></tr>
      {exp_rows}
      {('<tr><td colspan="3"></td></tr>' + inv_rows) if invest_total > 0 else ''}
      <tr><td colspan="3"></td></tr>
      {summary}
    </tbody>
  </table>

  <h3>2.2  Savings Rate Analysis</h3>
  <table>
    <thead><tr><th>Metric</th><th class="num">Current</th><th>Target / Notes</th></tr></thead>
    <tbody>
      <tr><td>Gross Savings Rate</td><td class="num">{_fmt_pct(gross_rate * 100)}</td><td>Target: 50%+ for peak-accumulation households</td></tr>
      <tr><td>Equity Investment Rate (SIP only)</td><td class="num">{_fmt_pct(invest_rate * 100)}</td><td>Lift toward 30-40% via goal-linked SIPs</td></tr>
      <tr><td>EMI as % of Income</td><td class="num">{_fmt_pct(emi_rate * 100)}</td><td>Below 35% is healthy</td></tr>
      <tr><td>Net Surplus (Monthly)</td><td class="num">{_fmt_inr(net_surplus)}</td><td>Remaining capacity to deploy</td></tr>
    </tbody>
  </table>

  <h3>2.3  Expense Review — Optimisation Opportunities</h3>
  {_sandeep_expense_opportunities(plan)}
  {_yoy_cashflow_tables(cfp)}
</section>"""


def _sandeep_expense_opportunities(plan: PlanState) -> str:
    """Surface the top 3-5 expense lines as 'observation' candidates."""
    e = plan.monthly_expenses
    candidates = []
    if e.travel_or_lifestyle and e.travel_or_lifestyle >= 15000:
        candidates.append(("Travel / Lifestyle", e.travel_or_lifestyle, "Annual budget — review whether all of it is essential"))
    if e.utilities and e.utilities >= 8000:
        candidates.append(("Utilities", e.utilities, "Audit subscriptions; OTT/phone packages often have bundled savings"))
    if e.other_emis and e.other_emis >= 30000:
        candidates.append(("Other EMIs", e.other_emis, "Check rates — refinancing or prepayment may free up surplus"))
    if e.medical and e.medical >= 15000:
        candidates.append(("Medical", e.medical, "Clarify if chronic; enhance health insurance to reduce out-of-pocket"))
    if e.rent_or_emi and e.rent_or_emi >= 80000:
        candidates.append(("Rent / Home Loan EMI", e.rent_or_emi, "Largest fixed outflow — track tenure and prepayment opportunities"))
    if not candidates:
        return '<p class="muted">No outlier expense lines flagged. The household is operating on a lean cost base.</p>'
    rows = "".join(
        f'<tr><td>{_h(label)}</td><td class="num">{_fmt_inr(amt)}</td><td>{_h(note)}</td></tr>'
        for label, amt, note in candidates
    )
    return f"""<table>
    <thead><tr><th>Expense Head</th><th class="num">Monthly (₹)</th><th>Observation</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>"""


def _sandeep_s3_networth(plan: PlanState) -> str:
    """SECTION 3 — Net Worth Assessment."""
    nw = plan.computed.net_worth
    mf_total = sum((h.current_value or 0) for h in plan.mutual_funds)
    eq_total = sum((h.current_value or 0) for h in plan.equity_stocks)
    fi_total = sum((h.current_value or 0) for h in plan.fixed_income)
    liquid_total = _sum_optionals(plan.liquid_capital)
    assets_total = mf_total + eq_total + fi_total + liquid_total
    if assets_total == 0:
        assets_total = nw.assets_total or 0

    def _pct(val: float) -> str:
        if assets_total <= 0:
            return "—"
        return f"{(val / assets_total * 100):.1f}%"

    asset_rows = []
    for mf in plan.mutual_funds:
        v = mf.current_value or 0
        if v > 0:
            asset_rows.append((mf.fund_name or "Mutual Fund", v, "Equity – MF"))
    for eq in plan.equity_stocks:
        v = eq.current_value or 0
        if v > 0:
            asset_rows.append((eq.stock_name or "Direct Equity", v, "Direct Equity"))
    for fi in plan.fixed_income:
        v = fi.current_value or 0
        if v > 0:
            asset_rows.append((fi.instrument or "Fixed Income", v, "Debt"))
    if liquid_total > 0:
        asset_rows.append(("Savings + Idle Cash", liquid_total, "Liquid"))

    asset_html_rows = "".join(
        f'<tr><td>{_h(label)}</td><td class="num">{_fmt_inr(v)}</td><td class="num">{_pct(v)}</td><td>{_h(kind)}</td></tr>'
        for label, v, kind in asset_rows
    )
    asset_html_rows += f'<tr style="font-weight:600;background:#f4f4f5;"><td>TOTAL ASSETS</td><td class="num">{_fmt_inr(assets_total)}</td><td class="num">100%</td><td></td></tr>'

    loans = plan.loans_liabilities
    liab_rows = []
    for key, name in (("home_loan", "Home Loan"), ("car_loan", "Car Loan"),
                      ("personal_loan", "Personal Loan"), ("credit_card_dues", "Credit Card Dues")):
        block = getattr(loans, key, None)
        if block and (block.outstanding_amount or 0) > 0:
            liab_rows.append(
                f'<tr><td>{_h(name)}</td><td class="num">{_fmt_inr(block.outstanding_amount)}</td>'
                f'<td class="num">{_fmt_inr(block.emi or 0)}</td>'
                f'<td class="num">{block.interest_rate or "—"}%</td>'
                f'<td>{block.tenure_left or "—"} yrs</td></tr>'
            )
    total_liab = nw.debts_total + nw.secured_debts
    liab_rows.append(
        f'<tr style="font-weight:600;background:#f4f4f5;"><td>TOTAL LIABILITIES</td>'
        f'<td class="num">{_fmt_inr(total_liab)}</td><td></td><td></td><td></td></tr>'
    )
    liab_html = "".join(liab_rows) if liab_rows else '<tr><td colspan="5" class="muted">No liabilities recorded.</td></tr>'

    mf_rows = "".join(
        f'<tr><td>{_h(mf.fund_name or "Fund")}</td>'
        f'<td>{_h((getattr(mf, "category", "") or "—"))}</td>'
        f'<td>{_h(getattr(mf, "plan_type", "Direct") or "Direct")}</td>'
        f'<td class="num">{_fmt_inr(mf.sip_amount or 0)}</td>'
        f'<td class="num">{_fmt_inr(mf.current_value or 0)}</td>'
        f'<td>{"Switch to Direct" if "regular" in str(getattr(mf, "plan_type", "") or "").lower() else "Keep"}</td></tr>'
        for mf in plan.mutual_funds
    )
    if not mf_rows:
        mf_rows = '<tr><td colspan="6" class="muted">No mutual funds recorded — start with index funds or a flexi-cap.</td></tr>'

    nw_summary = f"""
    <table>
      <tbody>
        <tr><td>Total Assets</td><td class="num">{_fmt_inr(assets_total)}</td></tr>
        <tr><td>Total Liabilities</td><td class="num">({_fmt_inr(total_liab)})</td></tr>
        <tr style="font-weight:600;background:#f4f4f5;"><td>NET WORTH</td><td class="num">{_fmt_inr(nw.total)}</td></tr>
        <tr><td>Financial Assets (excl. Real Estate)</td><td class="num">{_fmt_inr(mf_total + eq_total + fi_total + liquid_total)}</td></tr>
      </tbody>
    </table>"""

    return f"""<section class="page">
  <h2>SECTION 3 — NET WORTH ASSESSMENT</h2>
  <h3>3.1  Asset Inventory ({datetime.now().strftime("%B %Y")})</h3>
  <table>
    <thead><tr><th>Asset</th><th class="num">Current Value (₹)</th><th class="num">% of Assets</th><th>Type</th></tr></thead>
    <tbody>{asset_html_rows}</tbody>
  </table>

  <h3>3.2  Liabilities</h3>
  <table>
    <thead><tr><th>Liability</th><th class="num">Outstanding (₹)</th><th class="num">EMI (₹)</th><th class="num">Rate</th><th>Tenure</th></tr></thead>
    <tbody>{liab_html}</tbody>
  </table>

  <h3>3.3  Mutual Fund Portfolio — Quality Audit</h3>
  <table>
    <thead><tr><th>Fund</th><th>Category</th><th>Plan</th><th class="num">SIP (₹)</th><th class="num">Current Value (₹)</th><th>Action</th></tr></thead>
    <tbody>{mf_rows}</tbody>
  </table>

  <h3>Net Worth Summary</h3>
  {nw_summary}
</section>"""


def _retirement_stepup_block(sp: dict | None) -> str:
    """Excel `Retirement Plan` §3 — the step-up investment projection table."""
    if not sp or not sp.get("rows"):
        return ""
    surplus = sp["excess_or_gap"] >= 0
    pct = abs(sp["excess_pct"]) * 100
    body = "".join(
        f'<tr style="{"background:#f8f8f8;font-style:italic;" if row["is_one_time"] else ""}">'
        f'<td>{"—" if row["is_one_time"] else round(row["age"])}</td>'
        f'<td class="num">{row["years_remaining"]:.1f}</td>'
        f'<td class="num">{("%s (corpus)" % _fmt_inr(row["total_contribution"])) if row["is_one_time"] else _fmt_inr(row["base_contribution"])}</td>'
        f'<td class="num">{("+" + _fmt_inr(row["step_up_amount"])) if row["step_up_amount"] else "—"}</td>'
        f'<td class="num">{"—" if row["is_one_time"] else _fmt_inr(row["total_contribution"])}</td>'
        f'<td class="num">{_fmt_inr(row["fv_at_retirement"])}</td>'
        f'<td class="num">{_fmt_inr(row["cumulative_fv"])}</td></tr>'
        for row in sp["rows"]
    )
    return f"""
    <p class="muted" style="margin-top:2mm;"><strong>Step-up investment plan</strong> — starting at
    {_fmt_inr(sp['first_year_monthly_contribution'])}/mo, stepped up {sp['step_up_pct']*100:.0f}%/yr, grown to
    retirement at {sp['rate']*100:.1f}%:</p>
    <table>
      <tbody>
        <tr style="font-weight:600;background:#f4f4f5;"><td>Projected corpus at retirement</td><td class="num">{_fmt_inr(sp['projected_corpus_at_retirement'])}</td></tr>
        <tr><td>Corpus needed</td><td class="num">{_fmt_inr(sp['corpus_needed'])}</td></tr>
        <tr style="font-weight:600;"><td>{'Surplus' if surplus else 'Gap'}</td><td class="num">{_fmt_inr(abs(sp['excess_or_gap']))} ({'+' if surplus else '−'}{pct:.1f}%)</td></tr>
        <tr style="font-weight:600;background:#eef6ee;"><td>Required starting SIP to reach goal (with {sp['step_up_pct']*100:.0f}%/yr step-up)</td><td class="num">{_fmt_inr(sp['required_first_year_monthly'])}/mo</td></tr>
      </tbody>
    </table>
    <table>
      <thead><tr><th>Age</th><th class="num">Yrs to retire</th><th class="num">Annual contribution</th><th class="num">Step-up</th><th class="num">Total</th><th class="num">FV at retirement</th><th class="num">Cumulative</th></tr></thead>
      <tbody>{body}</tbody>
    </table>"""


def _levers_html(levers: list[dict]) -> str:
    if not levers:
        return ""
    items = []
    for lv in levers:
        ok = lv.get("feasible", True)
        mark = "✓" if ok else "✗"
        cls = "" if ok else ' style="color:#999;"'
        items.append(
            f'<li{cls}><strong>{mark} {_h(lv.get("title",""))}:</strong> {_h(lv.get("change",""))}'
            f'<br/><span class="muted">{_h(lv.get("rationale",""))}</span></li>'
        )
    return "<ul>" + "".join(items) + "</ul>"


def _sandeep_s4b_suggestions(plan: PlanState, sug: dict | None = None) -> str:
    """Section 4b — the AI 'Suggested' optimisation layer (six-lever engine).
    Three sub-blocks (Suggested Cashflow / Goals / Retirement) + the
    recommended combined plan + the lumpsum nudge. Accepts a pre-computed
    snapshot to avoid recomputing."""
    try:
        s = sug if sug is not None else suggestions_skill.compute_suggestions(plan)
    except Exception:
        return ""
    if not s:
        return ""
    if not s.get("has_gaps"):
        return """<section class="page">
  <h2>SECTION 4B — SUGGESTED IMPROVEMENTS</h2>
  <p>On the current trajectory every goal and the retirement corpus are adequately funded by existing SIPs and assets. No corrective levers are required — keep the current SIPs running and step them up with annual income growth.</p>
</section>"""

    rec = s.get("recommended", {})
    impact = rec.get("impact", {})
    ret_yr = impact.get("retirement_year")
    nw_sug = impact.get("net_worth_at_retirement") or 0
    nw_base = impact.get("baseline_net_worth_at_retirement") or 0
    rec_residual = rec.get("residual_note")
    impact_line = (
        f"<br/>Projected net worth at retirement ({ret_yr}): <strong>{_fmt_inr(nw_sug)}</strong> "
        f"vs {_fmt_inr(nw_base)} on today's plan."
        if ret_yr else ""
    )
    rec_html = f"""
    <div style="background:#eef6ee;border:1px solid #cfe3cf;padding:3mm;border-radius:2mm;margin:2mm 0;">
      <strong>Recommended combined plan:</strong> {_h(rec.get('summary',''))}.
      {impact_line}
      <br/><span class="muted">Levers: {_h(', '.join(rec.get('levers_used', [])) or 'none')}.</span>
      {('<br/><span style="color:#9a6a00;">' + _h(rec_residual) + '</span>') if rec_residual else ''}
    </div>"""

    goals = s["domains"]["goals"]["goals"]
    goal_rows = "".join(
        f'<tr><td>{_h(g["goal_name"])}{" (retirement)" if g.get("is_retirement") else ""}</td><td class="num">{g["target_year"]}</td>'
        f'<td class="num">{_fmt_inr(g["required_sip_monthly"])}</td>'
        f'<td class="num">{_fmt_inr(g["existing_sip_monthly"])}</td>'
        f'<td class="num">{_fmt_inr(g["shortfall_monthly"])}</td>'
        f'<td class="num">{(str(g["funded_pct"])+"%") if g.get("funded_pct") is not None else "—"}</td></tr>'
        for g in goals
    )
    goal_levers = "".join(
        f'<p style="margin-top:1.5mm;"><strong>{_h(g["goal_name"])}</strong> — ways to close the gap:</p>{_levers_html(g["levers"])}'
        for g in goals
    )
    goals_html = f"""
    <h3>Suggested Goals <span class="muted" style="font-weight:400;">(retirement included; SIPs already contributed are credited)</span></h3>
    <table>
      <thead><tr><th>Goal</th><th class="num">Year</th><th class="num">SIP needed</th><th class="num">Already SIP'd</th><th class="num">Add/mo</th><th class="num">Funded</th></tr></thead>
      <tbody>{goal_rows or '<tr><td colspan="6" class="muted">All goals on track.</td></tr>'}</tbody>
    </table>
    {goal_levers}""" if goals else ""

    r = s["domains"]["retirement"]
    ret_html = f"""
    <h3>Suggested Retirement Glide</h3>
    <p class="muted">Funding judged via the step-up plan (the firm's Section 3 method): the corpus is reached by stepping the retirement SIP up {round(0.10*100)}%/yr, not by a flat lump SIP.</p>
    <table>
      <tbody>
        <tr><td>Corpus required</td><td class="num">{_fmt_inr(r['corpus_required'])}</td></tr>
        <tr><td>Funded via step-up plan</td><td class="num">{r['funded_pct']}%</td></tr>
        <tr><td>Step-up starting SIP to reach</td><td class="num">{_fmt_inr(r.get('stepup_required_start_sip_monthly', 0))}/mo</td></tr>
        <tr><td>Already contributing to retirement</td><td class="num">{_fmt_inr(r.get('ongoing_sip_monthly', 0))}/mo</td></tr>
        <tr style="font-weight:600;background:#f4f4f5;"><td>Add to the starting SIP (then step up {round(0.10*100)}%/yr)</td><td class="num">{_fmt_inr(r.get('stepup_additional_start_sip_monthly', 0))}/mo</td></tr>
        <tr><td class="muted">Conservative flat-SIP alternative</td><td class="num muted">{_fmt_inr(r['required_sip_monthly'])}/mo</td></tr>
      </tbody>
    </table>
    {_levers_html(r.get('levers', []))}""" if not r.get("on_track") else f"""
    <h3>Suggested Retirement Glide</h3>
    <p>Retirement is on track — the current retirement SIP, stepped up {round(0.10*100)}%/yr, reaches the corpus ({r.get('funded_pct', 100)}% funded).</p>"""

    nudge = s.get("nudges", [{}])[0]
    nudge_html = f"""
    <div style="background:#fff7e6;border:1px solid #f0d9a8;padding:3mm;border-radius:2mm;margin:2mm 0;">
      <strong>{_h(nudge.get('title',''))}</strong> {_h(nudge.get('question',''))}
    </div>""" if nudge else ""

    return f"""<section class="page">
  <h2>SECTION 4B — SUGGESTED IMPROVEMENTS</h2>
  <p class="muted">How to do better than the as-is plan — concrete, math-backed levers. Guardrails: never delay children's education/marriage; retirement delay capped at age 62; value cuts bounded.</p>
  {rec_html}
  {goals_html}
  {ret_html}
  {nudge_html}
</section>"""


def _sandeep_s4_goals(plan: PlanState, cfp: cfp_skill.CFPOutput) -> str:
    """SECTION 4 — Goal-Based Planning."""
    intro = ("<p>All goals inflation-adjusted using the firm's CFP table: General 7%, Education 10%, "
             "Wedding 9%, Medical 12%, Real Estate / Vacation 9%. Investment returns use the glide-path "
             "effective return — equity for the early years de-risking toward debt as the goal approaches. "
             "All SIP calculations use Excel-faithful <code>PMT(rate/12, n×12, 0, −FV_gap)</code>.</p>")

    overview_rows = "".join(
        f"<tr><td>{_h(g['goal_name'])}</td>"
        f"<td>{g['target_year']} ({g['years_to_go']} yrs)</td>"
        f'<td class="num">{_fmt_lakhs(g["today_cost"])}</td>'
        f'<td class="num">{_fmt_lakhs(g["future_value_needed"])} @ {g["inflation_used"]*100:.0f}%</td>'
        f'<td>SIP ₹{g["required_sip_monthly"]:,}/mo @ {g["effective_return"]*100:.1f}%</td></tr>'
        for g in cfp.goal_blocks
    )
    if not overview_rows:
        overview_rows = '<tr><td colspan="5" class="muted">No goals set yet — add one in chat.</td></tr>'

    detail_blocks = []
    for i, g in enumerate(cfp.goal_blocks):
        h_label = f"4.{i+2}  {_h(g['goal_name'])} ({g['target_year']})"
        trace_rows = "".join(
            f'<tr><td>{_h(s["label"])}</td><td>{_h(s["formula"])}</td>'
            f'<td class="num">{_fmt_trace_value(s["value"], s["unit"])}</td></tr>'
            for s in g["computation_trace"]
        )
        detail_blocks.append(f"""
        <h3>{h_label}</h3>
        <table>
          <tbody>
            <tr><td>Current Today's Cost</td><td class="num">{_fmt_inr(g['today_cost'])}</td></tr>
            <tr><td>Inflation Applied</td><td class="num">{g['inflation_used']*100:.1f}% p.a.</td></tr>
            <tr><td>Inflation-Adjusted Cost in {g['target_year']}</td><td class="num">{_fmt_inr(g['future_value_needed'])}</td></tr>
            <tr><td>Existing Assets Allocated (FV)</td><td class="num">{_fmt_inr(g['allocated_today_total'])} today</td></tr>
            <tr><td>FV Gap to Cover via SIP</td><td class="num">{_fmt_inr(g['fv_gap'])}</td></tr>
            <tr><td>Glide-path Effective Return</td><td class="num">{g['effective_return']*100:.1f}% (horizon {g['years_to_go']}y)</td></tr>
            <tr style="font-weight:600;background:#f4f4f5;"><td>Required Monthly SIP</td><td class="num">₹{g['required_sip_monthly']:,}/month</td></tr>
          </tbody>
        </table>
        <p class="muted" style="margin-top:1mm;">Step-by-step (Excel-faithful):</p>
        <table>
          <thead><tr><th>Step</th><th>Formula</th><th class="num">Value</th></tr></thead>
          <tbody>{trace_rows}</tbody>
        </table>
        """)

    # Retirement block
    r = cfp.retirement
    r_trace = "".join(
        f'<tr><td>{_h(s["label"])}</td><td>{_h(s["formula"])}</td>'
        f'<td class="num">{_fmt_trace_value(s["value"], s["unit"])}</td></tr>'
        for s in r["computation_trace"]
    )
    _horizon_note = (
        f"spouse's lifetime — wife alive to {r.get('spouse_life_expectancy', '—')}, "
        f"age {r.get('spouse_age_at_retirement', '—')} at your retirement"
        if r.get("horizon_basis") == "spouse_lifetime"
        else "your own lifetime"
    )
    _one_time_row = (
        f"<tr><td>One-Time Post-Retirement Spend (grown to year)</td>"
        f"<td class=\"num\">{_fmt_inr(r['one_time_spend_fv'])}</td></tr>"
        if r.get("one_time_spend_fv") else ""
    )
    retirement_block = f"""
    <h3>4.{len(cfp.goal_blocks)+2}  Retirement Goal — Detailed Calculation</h3>
    <p class="muted" style="margin-bottom:1mm;">Cell-for-cell port of the firm's <code>Retirement Plan</code> tab —
    corpus discounted at {r.get('corpus_discount_return', 0)*100:.2f}% (conservative post-tax), SIP funded at
    {r.get('sip_funding_return', 0)*100:.1f}% (hybrid post-tax), horizon sized to {_horizon_note}.</p>
    <table>
      <tbody>
        <tr><td>Years to Retirement</td><td class="num">{r['years_to_retire']}</td></tr>
        <tr><td>Post-Retirement Horizon</td><td class="num">{r['post_retire_years']} years</td></tr>
        <tr><td>Retirement Living Expense (today, excl. school fees)</td><td class="num">{_fmt_inr(r.get('retirement_annual_expense_today', 0))}</td></tr>
        <tr><td>Annual Expenses at Retirement (inflation-grown)</td><td class="num">{_fmt_inr(r['annual_expenses_at_retirement'])}</td></tr>
        <tr><td>Inflation-Adjusted Real Return (Post-Retire)</td><td class="num">{r['real_return_used']*100:.2f}%</td></tr>
        <tr><td>Corpus for Recurring Spend (annuity due)</td><td class="num">{_fmt_inr(r.get('corpus_recurring', 0))}</td></tr>
        {_one_time_row}
        <tr style="font-weight:600;background:#f4f4f5;"><td>Total Retirement Corpus Required</td><td class="num">{_fmt_inr(r['corpus_required'])}</td></tr>
        <tr><td>Projected Value of Earmarked Assets at Retirement</td><td class="num">{_fmt_inr(r.get('projected_existing_corpus_fv', 0))}</td></tr>
        <tr><td>Shortfall in Corpus</td><td class="num">{_fmt_inr(r.get('corpus_shortfall_after_existing', 0))}</td></tr>
        <tr><td>Gross Monthly SIP Needed</td><td class="num">{_fmt_inr(r.get('gross_monthly_sip', 0))}</td></tr>
        <tr><td>Less: SIPs Already Ongoing</td><td class="num">{_fmt_inr(r.get('ongoing_retirement_sip_monthly', 0))}</td></tr>
        <tr style="font-weight:600;background:#f4f4f5;"><td>Additional Monthly SIP to Reach Goal</td><td class="num">{_fmt_inr(r.get('required_monthly_sip', 0))}</td></tr>
      </tbody>
    </table>
    <p class="muted" style="margin-top:1mm;">Step-by-step (Excel-faithful):</p>
    <table>
      <thead><tr><th>Step</th><th>Formula</th><th class="num">Value</th></tr></thead>
      <tbody>{r_trace}</tbody>
    </table>
    {_retirement_stepup_block(r.get('stepup_plan'))}"""

    return f"""<section class="page">
  <h2>SECTION 4 — GOAL-BASED PLANNING</h2>
  {intro}

  <h3>4.1  Goal Overview</h3>
  <table>
    <thead><tr><th>Goal</th><th>Timeline</th><th class="num">Today's Cost</th><th class="num">Inflation-Adj. Need</th><th>Strategy</th></tr></thead>
    <tbody>{overview_rows}</tbody>
  </table>

  {''.join(detail_blocks)}
  {retirement_block}
</section>"""


def _fmt_trace_value(value: Any, unit: str) -> str:
    if isinstance(value, str):
        return _h(value)
    try:
        v = float(value)
    except Exception:
        return _h(str(value))
    if unit == "%":
        return f"{v*100:.2f}%"
    if unit == "years":
        return f"{v:.1f}y"
    return _fmt_inr(v)


def _sandeep_s5_strategy(plan: PlanState, cfp: cfp_skill.CFPOutput) -> str:
    """SECTION 5 — Investment Strategy."""
    al = plan.computed.allocation
    if al:
        rec = al.recommended_allocation
        eq_split = al.recommended_equity_split
        target_table = f"""
        <table>
          <thead><tr><th>Asset Class</th><th class="num">Target %</th><th>Rationale</th></tr></thead>
          <tbody>
            <tr><td>Equity — Large Cap</td><td class="num">{eq_split.large * rec.equity / 100:.0f}%</td><td>Core stability via index funds</td></tr>
            <tr><td>Equity — Mid Cap</td><td class="num">{eq_split.mid * rec.equity / 100:.0f}%</td><td>Growth engine for the long horizon</td></tr>
            <tr><td>Equity — Small Cap</td><td class="num">{eq_split.small * rec.equity / 100:.0f}%</td><td>Higher risk/reward — 5y+ horizon only</td></tr>
            <tr><td>Debt</td><td class="num">{rec.debt}%</td><td>Provides stability + drawdown buffer</td></tr>
            <tr><td>Gold</td><td class="num">{rec.gold}%</td><td>Inflation hedge; prefer SGB over physical</td></tr>
            <tr><td>Cash / Liquid</td><td class="num">{rec.cash}%</td><td>Emergency liquidity</td></tr>
          </tbody>
        </table>
        <p class="muted">Strategic anchor: {_h(al.investor_risk_band)}. Tactical regime: {_h(al.tactical_regime_label)} (signal {int(round(al.tactical_regime_score)):+d}).</p>"""
    else:
        target_table = '<p class="muted">Allocation not yet computed. Answer 3 risk questions in chat to unlock.</p>'

    total_sip = sum(g["required_sip_monthly"] for g in cfp.goal_blocks)
    if total_sip > 0 and al:
        rec = al.recommended_allocation
        sip_rows = f"""
        <tr><td>Nifty 50 Index Fund</td><td>Large Cap</td><td class="num">₹{int(total_sip * (al.recommended_equity_split.large * rec.equity / 100) / 100):,}</td><td>Direct</td></tr>
        <tr><td>Parag Parikh Flexi Cap / Mid Cap blend</td><td>Mid Cap</td><td class="num">₹{int(total_sip * (al.recommended_equity_split.mid * rec.equity / 100) / 100):,}</td><td>Direct</td></tr>
        <tr><td>Nippon India Small Cap</td><td>Small Cap</td><td class="num">₹{int(total_sip * (al.recommended_equity_split.small * rec.equity / 100) / 100):,}</td><td>Direct</td></tr>
        <tr><td>Short-term Debt Fund / PPF Top-up</td><td>Debt</td><td class="num">₹{int(total_sip * rec.debt / 100):,}</td><td>Direct</td></tr>
        <tr style="font-weight:600;background:#f4f4f5;"><td>TOTAL MONTHLY SIP</td><td></td><td class="num">₹{int(total_sip):,}</td><td></td></tr>"""
    else:
        sip_rows = '<tr><td colspan="4" class="muted">Set goals + risk profile to populate the recommended SIP table.</td></tr>'

    actions = []
    for mf in plan.mutual_funds:
        plan_type = (getattr(mf, "plan_type", "") or "").lower()
        if "regular" in plan_type:
            actions.append(f"Switch <strong>{_h(mf.fund_name or 'Fund')}</strong> from Regular → Direct (use LTCG headroom).")
    if len(plan.mutual_funds) > 6:
        actions.append(f"Consolidate — you hold {len(plan.mutual_funds)} funds; 5-6 is plenty.")
    if not actions:
        actions = ["Portfolio looks clean. Continue current SIPs and step them up annually with salary increments."]
    actions_html = "".join(f"<li>{a}</li>" for a in actions)

    return f"""<section class="page">
  <h2>SECTION 5 — INVESTMENT STRATEGY</h2>

  <h3>5.1  Recommended Asset Allocation</h3>
  {target_table}

  <h3>5.2  Recommended Monthly SIP Portfolio</h3>
  <table>
    <thead><tr><th>Fund</th><th>Category</th><th class="num">SIP (₹)</th><th>Plan</th></tr></thead>
    <tbody>{sip_rows}</tbody>
  </table>

  <h3>5.3  Portfolio Consolidation Actions</h3>
  <ul>{actions_html}</ul>

  <h3>5.4  Expected Returns & Scenario Analysis</h3>
  {_sandeep_scenarios(plan)}
</section>"""


def _sandeep_scenarios(plan: PlanState) -> str:
    mc = plan.computed.monte_carlo
    if not mc:
        return '<p class="muted">Run Monte Carlo via the agent to populate the scenario analysis.</p>'
    horizon_nw = plan.computed.headline_amount_at_horizon or 0
    return f"""<table>
    <thead><tr><th>Scenario</th><th class="num">Equity Return</th><th class="num">Corpus at Horizon</th><th>Outcome</th></tr></thead>
    <tbody>
      <tr><td>Optimistic (P90)</td><td class="num">~13%</td><td class="num">{_fmt_lakhs(horizon_nw * 1.25)}</td><td>Freedom by age {mc.p90_freedom_age:.0f}</td></tr>
      <tr style="font-weight:600;background:#f4f4f5;"><td>Base (P50)</td><td class="num">~11%</td><td class="num">{_fmt_lakhs(horizon_nw)}</td><td>Freedom by age {mc.p50_freedom_age:.0f}</td></tr>
      <tr><td>Conservative (P10)</td><td class="num">~8%</td><td class="num">{_fmt_lakhs(horizon_nw * 0.65)}</td><td>Freedom by age {mc.p10_freedom_age:.0f}</td></tr>
    </tbody>
  </table>
  <p class="muted">Monte Carlo over {mc.paths_count:,} paths. Step up SIPs annually with salary increments to widen the corpus distribution.</p>"""


def _sandeep_s6_risk(plan: PlanState, cfp: cfp_skill.CFPOutput) -> str:
    """SECTION 6 — Risk Management."""
    fsi = plan.freedom_score_inputs
    monthly_outflow = (fsi.monthly_expenses or 0) + (fsi.monthly_emi or 0)
    ef_target = monthly_outflow * 6
    ef_current = fsi.liquid_assets_current_value or 0
    ef_gap = max(0, ef_target - ef_current)
    ef_sip = ef_gap / 36 if ef_gap > 0 else 0

    ef_badge = '<span class="badge good">Adequate</span>' if ef_gap <= 0 else '<span class="badge bad">Critical gap</span>'
    ef_callout = ""
    if ef_gap > 0:
        ef_callout = f"""<div class="callout bad">
          <strong>⚠  Emergency fund shortfall — {_fmt_lakhs(ef_gap)}</strong>
          <p>You're {_fmt_pct(ef_current / max(ef_target, 1) * 100, 0)} of the way to a 6-month liquidity buffer.
          Park ₹{int(ef_sip):,}/month into a Liquid Fund for the next 36 months to close it without delaying goal SIPs.</p>
        </div>"""
    ef_table = f"""
    <table>
      <tbody>
        <tr><td class="label-cell">Emergency Fund Status</td><td>{ef_badge}</td></tr>
        <tr><td class="label-cell">Monthly Living Outflow</td><td class="num">{_fmt_inr(monthly_outflow)}</td></tr>
        <tr><td class="label-cell">Recommended Emergency Fund (6 months)</td><td class="num">{_fmt_inr(ef_target)}</td></tr>
        <tr><td class="label-cell">Currently Liquid (Savings + Idle Cash)</td><td class="num">{_fmt_inr(ef_current)}</td></tr>
        <tr><td class="label-cell">Shortfall</td><td class="num">{_fmt_inr(ef_gap)}</td></tr>
        <tr class="total"><td>SIP to Close Gap (36 months → Liquid Fund)</td><td class="num">{_fmt_inr(ef_sip)}/mo</td></tr>
      </tbody>
    </table>
    {ef_callout}"""

    ins = cfp.insurance
    term = plan.insurance_details.term_plan
    health = plan.insurance_details.health_insurance
    family = plan.insurance_details.family_floater
    fs = plan.computed.freedom_score

    req_life = (fs.required_life_cover if fs else None) or ins["average"]
    req_med = (fs.required_medical_cover if fs else 1500000) or 1500000
    actual_life = (term.cover_amount if term else 0) or 0
    actual_health = ((health.cover_amount if health else 0) or 0) + ((family.cover_amount if family else 0) or 0)

    def status(actual: float, req: float) -> str:
        if actual >= req:
            return '<span class="badge good">Adequate</span>'
        if actual >= req * 0.7:
            return f'<span class="badge warn">Short {_fmt_lakhs(req - actual)}</span>'
        return f'<span class="badge bad">Gap {_fmt_lakhs(req - actual)}</span>'

    cover_table = f"""
    <table>
      <thead><tr><th>Cover Type</th><th class="num">Current</th><th class="num">Required</th><th>Status</th></tr></thead>
      <tbody>
        <tr><td>Term Life Insurance</td><td class="num">{_fmt_lakhs(actual_life)}</td><td class="num">{_fmt_lakhs(req_life)}</td><td>{status(actual_life, req_life)}</td></tr>
        <tr><td>Health (Self + Family Floater)</td><td class="num">{_fmt_lakhs(actual_health)}</td><td class="num">{_fmt_lakhs(req_med)}</td><td>{status(actual_health, req_med)}</td></tr>
        <tr><td>Critical Illness (standalone)</td><td class="num">—</td><td class="num">{_fmt_lakhs(5000000)}</td><td><span class="bad">Recommended add-on</span></td></tr>
        <tr><td>Personal Accident / Disability</td><td class="num">—</td><td class="num">{_fmt_lakhs(10000000)}</td><td><span class="warn">Income-protection layer</span></td></tr>
      </tbody>
    </table>"""

    # Why-table for life cover (only when underinsured)
    why_block = ""
    if actual_life < req_life:
        why_block = f"""
        <h4>Why ₹{actual_life/100000:.0f} Lakh Term Cover Is Insufficient</h4>
        <table>
          <tbody>
            <tr><td>Loans + Obligations</td><td class="num">{_fmt_inr((cfp.insurance.get('total_need_including_loans', 0) - cfp.insurance['average']) if isinstance(cfp.insurance, dict) else 0)}</td></tr>
            <tr><td>Children's Future Education</td><td class="num">{_fmt_lakhs(sum(g['future_value_needed'] for g in cfp.goal_blocks if 'education' in (g['goal_name'] or '').lower()))}</td></tr>
            <tr><td>Spouse Income Replacement (per Needs method)</td><td class="num">{_fmt_lakhs(cfp.insurance['needs_based_corpus'])}</td></tr>
            <tr style="font-weight:600;background:#f4f4f5;"><td>TOTAL NEED</td><td class="num">{_fmt_lakhs(req_life)}</td></tr>
            <tr><td>Current Term Cover</td><td class="num">{_fmt_lakhs(actual_life)}</td></tr>
            <tr style="font-weight:600;"><td>Additional Cover Needed</td><td class="num">{_fmt_lakhs(req_life - actual_life)}</td></tr>
          </tbody>
        </table>"""

    return f"""<section class="page">
  <h2>SECTION 6 — RISK MANAGEMENT</h2>

  <h3>6.1  Emergency Fund</h3>
  {ef_table}

  <h3>6.2  Insurance Assessment</h3>
  {cover_table}
  {why_block}
</section>"""


def _sandeep_s7_tax(plan: PlanState) -> str:
    """SECTION 7 — Tax Efficiency."""
    fsi = plan.freedom_score_inputs
    annual_income = (fsi.monthly_income or 0) * 12
    tax_view = plan.computed.tax
    current = f"<p>Annual income: <strong>{_fmt_inr(annual_income)}</strong>. " \
              f"Taxable income likely in the 30% slab post-basic deductions. " \
              f"Every ₹1 of legal deduction saves ₹0.30 in tax.</p>"
    if tax_view:
        ltcg_text = (f"LTCG headroom remaining this FY: <strong>₹{int(tax_view.ltcg_headroom_remaining):,}</strong>. "
                     f"Net post-tax delta from harvesting: <strong>₹{int(tax_view.net_post_tax_delta):,}</strong>.")
    else:
        ltcg_text = ""

    return f"""<section class="page">
  <h2>SECTION 7 — TAX EFFICIENCY</h2>

  <h3>7.1  Current Tax Position</h3>
  {current}
  <p>{ltcg_text}</p>

  <h3>7.2  Tax-Efficient Actions</h3>
  <table>
    <thead><tr><th>Section</th><th>Deduction Limit</th><th>Status</th><th>Action</th></tr></thead>
    <tbody>
      <tr><td>80C (ELSS + PPF + EPF + Home-loan principal)</td><td class="num">₹1,50,000</td><td>Likely maxed via PPF + EPF</td><td>Top up with ELSS if room</td></tr>
      <tr><td>80CCD(1B) — NPS top-up</td><td class="num">₹50,000</td><td>Verify usage</td><td>Add ₹50,000/yr to NPS</td></tr>
      <tr><td>80D — Health Insurance</td><td class="num">₹25K self + ₹25K parents</td><td>Partial use likely</td><td>Add super top-up</td></tr>
      <tr><td>24(b) — Home-loan Interest</td><td class="num">₹2,00,000</td><td>Verify with CA</td><td>Confirm yearly claim</td></tr>
      <tr><td>LTCG Harvesting</td><td class="num">₹1.25L/yr tax-free</td><td>Often missed</td><td>Book gains annually; reset cost basis</td></tr>
    </tbody>
  </table>
</section>"""


def _sandeep_s8_future(plan: PlanState, cfp: cfp_skill.CFPOutput) -> str:
    """SECTION 8 — Future-Proofing & Scenario Analysis."""
    yoy = cfp.yoy_cashflow
    if not yoy:
        return '<section class="page"><h2>SECTION 8 — FUTURE-PROOFING & SCENARIO ANALYSIS</h2><p class="muted">Cashflow not yet available.</p></section>'

    fsi = plan.freedom_score_inputs
    retire_age = plan.personal_details.retirement_age_target or 60
    start_age = fsi.age or yoy[0]["age"]
    # 3-phase
    phase1_end = min(start_age + 3, retire_age)
    phase2_end = max(start_age + 10, retire_age - 4)
    phase_rows = f"""
    <tr><td>Phase</td><td>Phase 1 — Emergency Fund + SIP Ramp</td><td>Phase 2 — Goal Funding</td><td>Phase 3 — Pre-Retirement</td></tr>
    <tr><td>Years</td><td>Age {start_age}–{phase1_end}</td><td>Age {phase1_end}–{phase2_end}</td><td>Age {phase2_end}–{retire_age}</td></tr>
    <tr><td>Focus</td><td>Build EF, start core SIPs</td><td>Children's education funding starts</td><td>Loan payoff redirected to retirement SIP</td></tr>"""

    # Stress test
    mc = plan.computed.monte_carlo
    if mc:
        stress = f"""
        <table>
          <thead><tr><th>Scenario</th><th class="num">Freedom Age</th><th class="num">Implied Corpus</th></tr></thead>
          <tbody>
            <tr><td>Optimistic (P90)</td><td class="num">{mc.p90_freedom_age:.0f}</td><td class="num">Comfortable surplus</td></tr>
            <tr style="font-weight:600;background:#f4f4f5;"><td>Base (P50)</td><td class="num">{mc.p50_freedom_age:.0f}</td><td class="num">Plan-on-track</td></tr>
            <tr><td>Conservative (P10)</td><td class="num">{mc.p10_freedom_age:.0f}</td><td class="num">Requires SIP step-up</td></tr>
          </tbody>
        </table>"""
    else:
        stress = '<p class="muted">Monte Carlo not yet run — invoke `montecarlo_run` to populate.</p>'

    # The 10–15 year wealth trajectory lived here; it's now covered in full by
    # the "Net Worth Trajectory" section at the top of the report (current vs
    # suggested, every year), so this duplicate has been removed.
    return f"""<section class="page">
  <h2>SECTION 8 — FUTURE-PROOFING & SCENARIO ANALYSIS</h2>

  <h3>8.1  3-Phase Financial Journey</h3>
  <table><tbody>{phase_rows}</tbody></table>

  <h3>8.2  Stress Test Scenarios</h3>
  {stress}
</section>"""


def _sandeep_s9_roadmap(plan: PlanState, cfp: cfp_skill.CFPOutput) -> str:
    """SECTION 9 — Execution Roadmap."""
    actions = _top_recommendations(plan)
    fsi = plan.freedom_score_inputs

    timeline_rows = "".join(
        f'<tr><td class="num">{g["target_year"]}</td>'
        f'<td>{_h(g["goal_name"])}</td>'
        f'<td class="num">{_fmt_inr(g["future_value_needed"])}</td>'
        f'<td>SIP ₹{g["required_sip_monthly"]:,}/mo</td></tr>'
        for g in cfp.goal_blocks
    )

    return f"""<section class="page">
  <h2>SECTION 9 — EXECUTION ROADMAP</h2>

  <h3>9.1  Immediate Actions (Next 30 Days)</h3>
  {actions}

  <h3>9.2  Monthly Investment Implementation Plan</h3>
  <table>
    <thead><tr><th>Investment</th><th class="num">Monthly</th><th>Notes</th></tr></thead>
    <tbody>
      <tr><td>Total Required SIP (CFP)</td><td class="num">₹{cfp.summary['total_required_sip_monthly']:,}</td><td>Across all goals (glide-path returns)</td></tr>
      <tr><td>Gross Monthly Surplus Available</td><td class="num">{_fmt_inr((fsi.monthly_income or 0) - (fsi.monthly_expenses or 0) - (fsi.monthly_emi or 0))}</td><td>Income − Expenses − EMI</td></tr>
      <tr style="font-weight:600;background:#f4f4f5;"><td>On Track?</td><td colspan="2">{'YES ✓' if cfp.summary['on_track'] else 'NO — see Section 8 for trade-off levers'}</td></tr>
    </tbody>
  </table>

  <h3>9.3  Goal Timeline Summary</h3>
  <table>
    <thead><tr><th class="num">Year</th><th>Goal</th><th class="num">Required FV</th><th>SIP / Plan</th></tr></thead>
    <tbody>{timeline_rows or '<tr><td colspan="4" class="muted">No goals.</td></tr>'}</tbody>
  </table>

  <h3>9.4  Review & Monitoring Framework</h3>
  <table>
    <thead><tr><th>Frequency</th><th>Activity</th><th>Trigger for Change</th></tr></thead>
    <tbody>
      <tr><td>Monthly</td><td>Confirm all SIPs executed; review surplus</td><td>SIP bounce, income change</td></tr>
      <tr><td>Quarterly</td><td>Fund performance vs benchmark</td><td>Underperformance >3% for 2 quarters</td></tr>
      <tr><td>Semi-Annual</td><td>Asset allocation rebalance</td><td>Drift >5% from target</td></tr>
      <tr><td>Annual (April)</td><td>Step up SIP, LTCG harvesting, tax planning</td><td>Salary increment, FY close</td></tr>
      <tr><td>Milestones</td><td>Goal triggers: redirect freed SIPs</td><td>Each goal exit year</td></tr>
    </tbody>
  </table>

  <div class="end-marker">— End of Financial Plan —</div>
</section>"""


# ── Entry point ────────────────────────────────────────────────────────────


async def render_plan_pdf(household_id: str) -> dict:
    plan = await get_plan(household_id)
    if not plan:
        return {
            "ok": False,
            "html": f'<!doctype html><body style="font-family:sans-serif;padding:2rem;">'
                    f'<h1>Household {_h(household_id)} not found</h1></body>',
        }

    # The Sandeep-style 9-section layout matches the firm's exemplar
    # `Sandeep_Hongamath_Financial_Plan_v1.docx` section-by-section. Set
    # `?style=legacy` on the API endpoint to fall back to the older
    # institutional layout.
    report_html = _build_sandeep_html(plan)

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
