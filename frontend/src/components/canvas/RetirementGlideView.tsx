'use client';

import type { ReactNode } from 'react';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

/**
 * Retirement Glide — client-facing retirement corpus presentation.
 *
 * Three cases (per the firm's corpus spec), no step-up schedule or Excel-mirror
 * tables:
 *   Case 1  Recommended Path — the flat monthly SIP to start today (no step-up)
 *           that exactly funds the required corpus. The headline ask.
 *   Case 2  Base Case — where the client lands investing only their currently
 *           available surplus, flat, with no other change.
 *   Case 3  Stretch Case — only when Case 1 isn't comfortably feasible: 2-3
 *           lever combinations that reach the same corpus with a lower ask today.
 *
 * All numbers are back-solved and forward-validated by the backend
 * (`compute_retirement_cases`); this view only renders them.
 */
export function RetirementGlideView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const cases = (plan.computed.cfp?.retirement as { cases?: RetirementCases } | undefined)?.cases;

  if (!cases || !cases.case1) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Run the comprehensive plan (CFP) first — this view presents the retirement corpus cases.
      </div>
    );
  }

  const { inputs, case1, case2, case3 } = cases;

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h2 className="text-base font-semibold text-zinc-800">Retirement Corpus — your options</h2>
        <p className="text-xs text-zinc-500 mt-1 max-w-2xl">
          The corpus you need at retirement, the cleanest flat SIP that funds it, where you land on
          your current surplus alone, and — if the flat ask is a stretch — the trade-off combinations
          that still get you there. All figures are back-solved and forward-checked against the target.
        </p>
      </header>

      <InputsStrip inputs={inputs} />

      <Case1Card c={case1} inputs={inputs} />
      <Case2Card c={case2} corpus={case1.corpus_required} />
      {case3.triggered && <Case3Card c={case3} totalSurplus={inputs.total_monthly_surplus} />}
    </div>
  );
}

/* ── Inputs strip ──────────────────────────────────────────────────────── */

function InputsStrip({ inputs }: { inputs: CaseInputs }) {
  const investable = inputs.investable_surplus ?? inputs.total_monthly_surplus;
  const goalSip = inputs.goal_sip_required_monthly ?? inputs.other_goal_sip_monthly;
  const items: [string, string][] = [
    ['Current age', `${oneDp(inputs.current_age)}`],
    ['Retirement age', `${oneDp(inputs.retirement_age)}`],
    ['Years to retire', `${oneDp(inputs.years_to_retire)}`],
    ['Years in retirement', `${oneDp(inputs.years_in_retirement)}`],
    ['Expected return', pct(inputs.expected_return)],
    ['Inflation', pct(inputs.inflation)],
    ['Existing retirement assets', formatINR(inputs.existing_retirement_assets_today, { compact: true })],
    ['Surplus for retirement', `${formatINR(inputs.surplus_available_for_retirement, { compact: true })}/mo`],
  ];
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-3 text-xs">
        {items.map(([label, value]) => (
          <div key={label} className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wide text-zinc-400">{label}</span>
            <span className="tabular-nums text-zinc-800 mt-0.5">{value}</span>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-zinc-400 mt-3">
        Surplus for retirement = investable surplus {formatINR(investable, { compact: true })}/mo −
        SIPs your other goals need {formatINR(goalSip, { compact: true })}/mo.
        {inputs.emergency_fund_sip_monthly != null && inputs.pre_sip_surplus != null && (
          <>
            {' '}Investable surplus is your {formatINR(inputs.pre_sip_surplus, { compact: true })}/mo pre-SIP surplus
            net of the {formatINR(inputs.emergency_fund_sip_monthly, { compact: true })}/mo emergency-fund build SIP.
          </>
        )}
      </p>
    </div>
  );
}

/* ── Case 1 — Recommended flat SIP ─────────────────────────────────────── */

function Case1Card({ c, inputs }: { c: Case1; inputs: CaseInputs }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <CaseHeader n={1} title="Recommended Path — flat SIP" badge={<FeasBadge band={c.feasibility} pct={c.band_pct} />} />
      <p className="text-xs text-zinc-500 mb-4">
        The same amount every month, from today until you retire — no step-up, no annual review. The
        cleanest, most predictable commitment that funds your corpus in full.
      </p>

      <div className="rounded-lg bg-[color:var(--color-accent,#5f7d56)]/8 border border-[color:var(--color-accent,#5f7d56)]/20 px-4 py-3 mb-4 flex items-baseline justify-between">
        <span className="text-sm text-zinc-600">Flat monthly SIP to start today</span>
        <span className="text-2xl font-semibold tabular-nums text-zinc-900">
          {formatINR(c.flat_monthly_sip)}<span className="text-sm font-normal text-zinc-500">/mo</span>
        </span>
      </div>

      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-xs">
        <Row label={`Corpus needed at retirement (age ${oneDp(inputs.retirement_age)})`} value={formatINR(c.corpus_required, { compact: true })} strong />
        <Row label="Monthly expense at retirement (inflated)" value={`${formatINR(c.monthly_expense_at_retirement, { compact: true })}/mo`} />
        <Row label="Existing retirement assets, grown to retirement" value={formatINR(c.existing_assets_fv, { compact: true })} />
        <Row label="Shortfall the SIP must close" value={formatINR(c.shortfall, { compact: true })} />
        <Row label="Projected corpus from this SIP" value={formatINR(c.final_corpus, { compact: true })} />
        <Row
          label="Feasibility vs investable surplus"
          value={c.band_pct != null ? `${oneDp(c.band_pct)}% of surplus` : '—'}
        />
      </dl>

      {!c.validated && <ValidationWarn />}
    </section>
  );
}

/* ── Case 2 — Base case ────────────────────────────────────────────────── */

function Case2Card({ c, corpus }: { c: Case2; corpus: number }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <CaseHeader n={2} title="Base Case — current surplus only" />
      {!c.available ? (
        <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2.5 text-xs text-amber-900">
          {c.reason}
        </div>
      ) : (
        <>
          <p className="text-xs text-zinc-500 mb-4">
            If you simply invest the surplus available to you today, flat, with no other change — here
            is where you land against the {formatINR(corpus, { compact: true })} target.
          </p>
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-xs">
            <Row label="Monthly surplus available for retirement" value={`${formatINR(c.surplus_available!, { compact: true })}/mo`} />
            <Row label="Projected corpus you reach" value={formatINR(c.projected_corpus!, { compact: true })} strong />
            <Row label="Coverage of target corpus" value={`${oneDp(c.coverage_pct!)}%`} />
            <Row label="Gap remaining" value={formatINR(c.gap!, { compact: true })} />
          </dl>
          <div className={`mt-4 rounded-md px-3 py-2.5 text-xs ${c.on_track ? 'bg-emerald-50 border border-emerald-200 text-emerald-900' : 'bg-zinc-50 border border-zinc-200 text-zinc-600'}`}>
            {c.on_track
              ? `On track — your current surplus alone reaches ${oneDp(c.coverage_pct!)}% of the corpus.`
              : `Your current surplus covers ${oneDp(c.coverage_pct!)}% of the target, leaving a ${formatINR(c.gap!, { compact: true })} gap — the reason Case 1 recommends a higher SIP.`}
          </div>
        </>
      )}
    </section>
  );
}

/* ── Case 3 — Stretch combinations ─────────────────────────────────────── */

function Case3Card({ c, totalSurplus }: { c: Case3; totalSurplus: number }) {
  if (c.structurally_infeasible) {
    return (
      <section className="rounded-xl border border-rose-200 bg-rose-50/60 p-5">
        <CaseHeader n={3} title="Stretch Case" />
        <div className="rounded-md bg-rose-50 border border-rose-200 px-3 py-2.5 text-xs text-rose-900">
          {c.infeasible_note ?? 'No combination of allowable levers closes the gap within the 65-year retirement cap. Escalate to the RM.'}
        </div>
      </section>
    );
  }
  const combos = c.combinations ?? [];
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <CaseHeader n={3} title="Stretch Case — ways to lower today's ask" />
      <p className="text-xs text-zinc-500 mb-4">
        Case 1's flat SIP is a stretch against your {formatINR(totalSurplus, { compact: true })}/mo surplus.
        Each combination below reaches the same corpus with a lower starting commitment — ordered from
        least to most disruptive. Pick the one that matches how you want to live the next years.
      </p>
      <div className="flex flex-col gap-3">
        {combos.map((k, idx) => (
          <div key={idx} className="rounded-lg border border-zinc-200 bg-zinc-50/40 p-4">
            <div className="flex items-baseline justify-between gap-3 mb-1">
              <h4 className="text-sm font-medium text-zinc-800">
                {String.fromCharCode(65 + idx)} · {k.name}
              </h4>
              <span className="text-sm font-semibold tabular-nums text-zinc-900 whitespace-nowrap">
                {formatINR(k.start_monthly_sip)}<span className="text-xs font-normal text-zinc-500">/mo</span>
                {k.is_stepup && (
                  <span className="text-[11px] font-normal text-zinc-500"> → {formatINR(k.final_year_monthly_sip, { compact: true })}/mo by final yr</span>
                )}
              </span>
            </div>
            <p className="text-xs text-zinc-600">{k.levers_sentence}</p>
            <p className="text-[11px] text-zinc-500 mt-1.5"><span className="font-medium text-zinc-600">Trade-off:</span> {k.trade_off}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[10px] text-zinc-400">
              <span>Retire at {oneDp(k.retirement_age)}</span>
              {k.expense_reduction_pct > 0 && <span>Retirement spend −{oneDp(k.expense_reduction_pct)}%</span>}
              {k.is_stepup && k.step_up_pct != null && <span>Step-up {Math.round(k.step_up_pct * 100)}%/yr</span>}
              {k.uses_idle_cash && <span>Deploys idle cash</span>}
              {k.redirects_lowpriority_goals && <span>Redirects lower-priority goals</span>}
              <span className={k.validated ? 'text-emerald-600' : 'text-rose-600'}>
                {k.validated ? '✓ corpus matches target' : '⚠ check'}
              </span>
            </div>
          </div>
        ))}
        {combos.length === 0 && (
          <div className="rounded-md bg-zinc-50 border border-zinc-200 px-3 py-2.5 text-xs text-zinc-500">
            No comfortably feasible combination found — discuss with your RM.
          </div>
        )}
      </div>
    </section>
  );
}

/* ── Shared bits ───────────────────────────────────────────────────────── */

function CaseHeader({ n, title, badge }: { n: number; title: string; badge?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-1">
      <h3 className="text-sm font-semibold text-zinc-800">
        <span className="text-[color:var(--color-accent,#5f7d56)]">Case {n}</span> · {title}
      </h3>
      {badge}
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between border-b border-zinc-100 py-1 last:border-0">
      <dt className="text-zinc-500">{label}</dt>
      <dd className={`tabular-nums ${strong ? 'font-semibold text-zinc-900' : 'text-zinc-700'}`}>{value}</dd>
    </div>
  );
}

function FeasBadge({ band, pct }: { band: string; pct: number | null }) {
  const map: Record<string, { label: string; cls: string }> = {
    feasible: { label: 'Feasible', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    tight: { label: 'Tight', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
    stretched: { label: 'Stretched', cls: 'bg-orange-50 text-orange-700 border-orange-200' },
    not_feasible: { label: 'Not feasible at flat', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
  };
  const m = map[band] ?? map.tight;
  return (
    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${m.cls}`}>
      {m.label}{pct != null ? ` · ${oneDp(pct)}%` : ''}
    </span>
  );
}

function ValidationWarn() {
  return (
    <div className="mt-3 rounded-md bg-rose-50 border border-rose-200 px-3 py-2 text-[11px] text-rose-800">
      ⚠ Forward validation did not reconcile within tolerance — review the inputs with your RM.
    </div>
  );
}

/* ── Format helpers ────────────────────────────────────────────────────── */

function pct(frac: number): string {
  return `${(frac * 100).toFixed(1)}%`;
}
function oneDp(n: number | null | undefined): string {
  if (n == null) return '—';
  return Number.isInteger(n) ? `${n}` : n.toFixed(1);
}

/* ── Types (mirror backend compute_retirement_cases) ───────────────────── */

type CaseInputs = {
  current_age: number;
  retirement_age: number;
  life_expectancy: number;
  spouse_life_expectancy: number | null;
  years_to_retire: number;
  years_in_retirement: number;
  expected_return: number;
  inflation: number;
  retire_monthly_expense_today: number;
  existing_retirement_assets_today: number;
  total_monthly_surplus: number;
  other_goal_sip_monthly: number;
  emergency_fund_sip_monthly: number;
  surplus_available_for_retirement: number;
  idle_liquid_assets: number;
  // Added by compute_cfp for a transparent breakdown.
  investable_surplus?: number;
  goal_sip_required_monthly?: number;
  pre_sip_surplus?: number;
};

type Case1 = {
  corpus_required: number;
  monthly_expense_at_retirement: number;
  existing_assets_fv: number;
  shortfall: number;
  flat_monthly_sip: number;
  final_corpus: number;
  band_ratio: number | null;
  band_pct: number | null;
  feasibility: string;
  validated: boolean;
};

type Case2 = {
  available: boolean;
  reason?: string;
  surplus_available?: number;
  projected_corpus?: number;
  coverage_pct?: number;
  gap?: number;
  on_track?: boolean;
};

type Case3Combo = {
  name: string;
  levers_sentence: string;
  trade_off: string;
  is_stepup: boolean;
  step_up_pct: number | null;
  retirement_age: number;
  delay_years: number;
  monthly_expense_today: number;
  expense_reduction_pct: number;
  uses_idle_cash: boolean;
  redirects_lowpriority_goals: boolean;
  start_monthly_sip: number;
  final_year_monthly_sip: number;
  final_corpus: number;
  corpus_target: number;
  feasible: boolean;
  validated: boolean;
  disruption: number;
};

type Case3 = {
  triggered: boolean;
  feasibility_band?: string;
  combinations?: Case3Combo[];
  structurally_infeasible?: boolean;
  infeasible_note?: string;
};

type RetirementCases = {
  inputs: CaseInputs;
  case1: Case1;
  case2: Case2;
  case3: Case3;
};
