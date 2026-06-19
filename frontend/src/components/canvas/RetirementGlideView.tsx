'use client';

import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { SuggestedSection } from './SuggestedSection';

/**
 * Retirement Glide — a dedicated view that zooms the net-worth trajectory on
 * the retirement transition: the years leading up to the user's retirement
 * age + the post-retirement drawdown. Existing cashflow data; new framing.
 *
 * Surfaces three things the headline chart hides:
 *  - Retirement-year net worth (the corpus they actually retire with)
 *  - Whether the corpus survives the post-retirement horizon
 *  - The "real" annual outflow in retirement years (income drops to ₹0)
 */
export function RetirementGlideView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const rows = plan.computed.cashflow?.rows ?? [];
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Run cashflow first — this view shows the asset trajectory through retirement.
      </div>
    );
  }

  const retireAge = plan.assumptions.persons[0]?.retirement_age ?? plan.personal_details.retirement_age_target ?? 60;
  const startAge = plan.freedom_score_inputs.age ?? rows[0].age;
  const retireYear = rows.find((r) => r.age >= retireAge)?.year ?? rows[rows.length - 1].year;

  // Show 5 years before retirement through end of horizon — focuses the chart
  // on the transition rather than the full 45-year span.
  const focusFrom = Math.max(rows[0].year, retireYear - 5);
  const focused = rows.filter((r) => r.year >= focusFrom);

  // Retirement-year corpus + terminal corpus.
  const retireRow = rows.find((r) => r.year === retireYear);
  const terminalRow = rows[rows.length - 1];
  const drawdownYears = terminalRow.age - retireAge;

  const cfpRet = plan.computed.cfp?.retirement as CfpRetirementBlock | undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Stat label="Current age" value={`${startAge}`} note={`retire at ${retireAge}`} />
        <Stat
          label={`Net worth at ${retireAge}`}
          value={formatINR(retireRow?.total_net_worth ?? 0, { compact: true })}
          note={`year ${retireYear}`}
        />
        <Stat
          label={`Terminal (age ${terminalRow.age})`}
          value={formatINR(terminalRow.total_net_worth, { compact: true })}
          note={`${drawdownYears}y in retirement`}
        />
      </div>

      {cfpRet && <RetirementCorpusBlock block={cfpRet} retireAge={retireAge} />}

      {cfpRet?.stepup_plan && cfpRet.stepup_plan.rows.length > 0 && (
        <StepUpTable plan={cfpRet.stepup_plan} retireAge={retireAge} />
      )}

      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">
          Asset trajectory through retirement
        </h3>
        <div className="w-full h-[280px]">
          <ResponsiveContainer>
            <AreaChart data={focused} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
              <defs>
                <linearGradient id="grad-glide" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#87a17e" stopOpacity={0.32} />
                  <stop offset="100%" stopColor="#87a17e" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <XAxis dataKey="year" tickLine={false} axisLine={false} interval="preserveStartEnd" tick={{ fontSize: 11, fill: '#a1a1aa' }} />
              <YAxis
                tickFormatter={(v: number) => formatINR(v, { compact: true }).replace('₹', '')}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: '#a1a1aa' }}
                width={64}
              />
              <Tooltip
                formatter={(v: number) => formatINR(v, { compact: true })}
                contentStyle={{ borderRadius: 8, border: '1px solid #e4e4e7', fontSize: 12 }}
              />
              <ReferenceLine
                x={retireYear}
                stroke="#52525b"
                strokeDasharray="4 4"
                label={{ value: `retires (age ${retireAge})`, position: 'insideTopRight', fontSize: 10, fill: '#71717a' }}
              />
              <Area
                type="monotone"
                dataKey="total_net_worth"
                stroke="#87a17e"
                strokeWidth={1.5}
                fill="url(#grad-glide)"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">Year-by-year drawdown</h3>
        <table className="w-full text-xs">
          <thead className="text-zinc-500">
            <tr className="text-left border-b border-zinc-100">
              <th className="py-1.5">Year</th>
              <th className="py-1.5">Age</th>
              <th className="text-right">Income</th>
              <th className="text-right">Expenses</th>
              <th className="text-right">Net worth</th>
            </tr>
          </thead>
          <tbody>
            {focused.map((r) => {
              const retired = r.age >= retireAge;
              return (
                <tr key={r.year} className={`border-b border-zinc-100 last:border-0 ${retired ? 'bg-zinc-50/60' : ''}`}>
                  <td className="py-1.5">{r.year}</td>
                  <td className="py-1.5">
                    {r.age}
                    {retired && <span className="ml-1 text-[10px] text-zinc-400">(retired)</span>}
                  </td>
                  <td className="text-right tabular-nums">{formatINR(r.income, { compact: true })}</td>
                  <td className="text-right tabular-nums">{formatINR(r.expenses, { compact: true })}</td>
                  <td className="text-right tabular-nums font-medium">{formatINR(r.total_net_worth, { compact: true })}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <SuggestedSection plan={plan} domain="retirement" />
    </div>
  );
}

function Stat({
  label,
  value,
  note,
  accent,
}: {
  label: string;
  value: string;
  note?: string;
  accent?: 'good' | 'bad';
}) {
  const accentClass = accent === 'bad' ? 'text-rose-700' : accent === 'good' ? 'text-emerald-700' : 'text-zinc-800';
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-zinc-400">{label}</div>
      <div className={`text-lg font-semibold tabular-nums mt-0.5 ${accentClass}`}>{value}</div>
      {note && <div className="text-[10px] text-zinc-400 mt-0.5">{note}</div>}
    </div>
  );
}

type CfpRetirementBlock = {
  current_age?: number;
  retirement_age?: number;
  life_expectancy?: number;
  spouse_current_age?: number | null;
  spouse_life_expectancy?: number | null;
  spouse_age_at_retirement?: number | null;
  horizon_basis?: 'spouse_lifetime' | 'self_lifetime';
  years_to_retire?: number;
  years_post_retirement?: number;
  post_retire_years?: number;
  annual_expense_today?: number;
  annual_expense_at_retirement?: number;
  annual_expenses_at_retirement?: number;
  retirement_annual_expense_today?: number;
  pre_retire_return?: number;
  post_retire_return?: number;
  corpus_discount_return?: number;
  sip_funding_return?: number;
  inflation_during_retirement?: number;
  real_return_during_retirement?: number;
  // Corpus
  corpus_recurring?: number;
  one_time_spend_today?: number;
  one_time_spend_years?: number;
  one_time_spend_fv?: number;
  corpus_required?: number;
  // Provision + shortfall
  projected_existing_corpus_fv?: number;
  total_provision_at_retirement?: number;
  corpus_shortfall_recurring?: number;
  corpus_shortfall_one_time?: number;
  corpus_shortfall_after_existing?: number;
  // SIP
  sip_recurring_monthly?: number;
  sip_one_time_monthly?: number;
  gross_monthly_sip?: number;
  ongoing_retirement_sip_monthly?: number;
  required_monthly_sip?: number;
  used_planned_retirement_expense?: boolean;
  // Section-1 extras
  annual_living_expense_current?: number;
  self_life_expectancy?: number;
  // SIP purpose split
  sip_purpose_breakdown?: {
    retirement_monthly: number;
    goal_monthly: number;
    total_monthly: number;
    source: 'tagged' | 'instrument_heuristic';
  };
  // Section-3 step-up plan
  stepup_plan?: StepUpPlan;
};

type StepUpRow = {
  label: string;
  is_one_time: boolean;
  year_offset?: number;
  years_remaining: number;
  age: number;
  base_contribution: number;
  step_up_amount: number;
  total_contribution: number;
  rate: number;
  fv_at_retirement: number;
  cumulative_fv: number;
};

type StepUpPlan = {
  step_up_pct: number;
  rate: number;
  first_year_annual_contribution: number;
  first_year_monthly_contribution: number;
  current_corpus_today: number;
  projected_corpus_at_retirement: number;
  corpus_needed: number;
  excess_or_gap: number;
  excess_pct: number;
  reaches_goal: boolean;
  required_first_year_contribution: number;
  required_first_year_monthly: number;
  rows: StepUpRow[];
};

/** Cell-for-cell mirror of the firm's `Retirement Plan` tab — corpus
 * (recurring annuity + one-time spend), the projected value of earmarked
 * assets, the shortfall, and the additional monthly SIP to close it. */
function RetirementCorpusBlock({ block, retireAge }: { block: CfpRetirementBlock; retireAge: number }) {
  const recurring = block.corpus_recurring ?? 0;
  const oneTimeFV = block.one_time_spend_fv ?? 0;
  const required = block.corpus_required ?? recurring + oneTimeFV;
  const projected = block.projected_existing_corpus_fv ?? block.total_provision_at_retirement ?? 0;
  const shortfall = block.corpus_shortfall_after_existing ?? Math.max(0, required - projected);
  const fundedPct = required > 0 ? Math.max(0, Math.min(100, (projected / required) * 100)) : 0;

  const grossSip = block.gross_monthly_sip ?? 0;
  const ongoingSip = block.ongoing_retirement_sip_monthly ?? 0;
  const additionalSip = block.required_monthly_sip ?? Math.max(0, grossSip - ongoingSip);

  const spouseHorizon = block.horizon_basis === 'spouse_lifetime';
  const annualAtRetire = block.annual_expenses_at_retirement ?? block.annual_expense_at_retirement ?? 0;
  const discountReturn = block.corpus_discount_return ?? block.post_retire_return ?? 0;
  const sipReturn = block.sip_funding_return ?? 0;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <h3 className="text-sm font-medium text-zinc-700 mb-1">Retirement corpus (Excel-faithful)</h3>
      <p className="text-[11px] text-zinc-400 mb-4">
        Mirrors <code className="text-[10px]">Retirement Plan</code> in the firm CFP workbook —
        living expenses (excl. school fees) grown to retirement, the annuity-due PV of the
        post-retirement years{spouseHorizon ? " sized to the spouse's lifetime" : ''}, plus any
        one-time post-retirement spend. Funded against the projected value of earmarked assets, with
        the additional monthly SIP that closes the gap.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <Cell label="Time to retire" value={`${block.years_to_retire ?? '—'} yrs`} />
        <Cell
          label={spouseHorizon ? 'Post-retirement (spouse lifetime)' : 'Years post-retirement'}
          value={`${block.post_retire_years ?? block.years_post_retirement ?? '—'} yrs`}
        />
        <Cell
          label={
            block.used_planned_retirement_expense
              ? 'Planned retirement spend (from goal)'
              : 'Retirement living expense (today)'
          }
          value={formatINR(
            block.retirement_annual_expense_today ?? block.annual_expense_today ?? 0,
            { compact: true },
          )}
        />
        <Cell
          label={`Annual expense at age ${retireAge}`}
          value={formatINR(annualAtRetire, { compact: true })}
        />
        <Cell
          label="Current annual living expense"
          value={formatINR(block.annual_living_expense_current ?? 0, { compact: true })}
        />
        <Cell
          label="Life expectancy (self / spouse)"
          value={`${block.self_life_expectancy ?? '—'} / ${block.spouse_life_expectancy ?? '—'}`}
        />
        <Cell label="Corpus discount return" value={`${(discountReturn * 100).toFixed(2)}%`} />
        <Cell label="SIP funding return" value={`${(sipReturn * 100).toFixed(1)}%`} />
        <Cell
          label="Inflation in retirement"
          value={`${((block.inflation_during_retirement ?? 0) * 100).toFixed(1)}%`}
        />
        <Cell
          label="Inflation-adj real return"
          value={`${((block.real_return_during_retirement ?? 0) * 100).toFixed(2)}%`}
        />
      </div>

      {spouseHorizon && (
        <p className="mt-2 text-[10px] text-zinc-400">
          Horizon = spouse life expectancy {block.spouse_life_expectancy ?? '—'} − spouse age{' '}
          {block.spouse_age_at_retirement ?? '—'} at your retirement.
        </p>
      )}

      {/* Corpus build-up */}
      <div className="mt-4 rounded-md bg-zinc-50/40 border border-zinc-100 p-3 text-xs">
        <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1.5">
          Corpus required = {formatINR(required, { compact: true })}
        </div>
        <div className="flex items-baseline justify-between py-0.5">
          <span className="text-zinc-700">Recurring spend (annuity due over post-retirement years)</span>
          <span className="text-zinc-900 tabular-nums">{formatINR(recurring, { compact: true })}</span>
        </div>
        {oneTimeFV > 0 && (
          <div className="flex items-baseline justify-between py-0.5">
            <span className="text-zinc-700">
              One-time post-retirement spend
              {block.one_time_spend_today ? ` (${formatINR(block.one_time_spend_today, { compact: true })} today)` : ''}
            </span>
            <span className="text-zinc-900 tabular-nums">{formatINR(oneTimeFV, { compact: true })}</span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
        <Big label="Corpus required" value={formatINR(required, { compact: true })} />
        <Big
          label="Earmarked assets at retirement"
          value={formatINR(projected, { compact: true })}
          subtle
        />
        <Big
          label="Shortfall"
          value={formatINR(shortfall, { compact: true })}
          accent={shortfall > 0 ? 'bad' : 'good'}
        />
      </div>

      <div className="mt-4">
        <div className="flex justify-between text-[11px] text-zinc-500 mb-1">
          <span>Coverage of required corpus</span>
          <span className="tabular-nums">{fundedPct.toFixed(1)}%</span>
        </div>
        <div className="h-2 bg-zinc-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-[color:var(--color-accent,#5f7d56)]"
            style={{ width: `${fundedPct}%` }}
          />
        </div>
      </div>

      {/* SIP build-down: gross − ongoing = additional */}
      {grossSip > 0 && (
        <div className="mt-4 rounded-md bg-zinc-50 border border-zinc-200 px-3 py-2.5 text-xs space-y-1">
          <div className="flex justify-between">
            <span className="text-zinc-500">Gross monthly SIP needed</span>
            <span className="text-zinc-700 tabular-nums">{formatINR(grossSip)} /mo</span>
          </div>
          {ongoingSip > 0 && (
            <div className="flex justify-between">
              <span className="text-zinc-500">Less: retirement SIPs already ongoing</span>
              <span className="text-zinc-700 tabular-nums">− {formatINR(ongoingSip)} /mo</span>
            </div>
          )}
          <div className="flex justify-between border-t border-zinc-200 pt-1 mt-1">
            <span className="text-zinc-600 font-medium">Additional monthly SIP to reach goal</span>
            <span className="text-zinc-900 font-semibold tabular-nums">{formatINR(additionalSip)} /mo</span>
          </div>
          {block.sip_purpose_breakdown && block.sip_purpose_breakdown.goal_monthly > 0 && (
            <div className="text-[10px] text-zinc-400 pt-1">
              Only retirement-directed SIPs are netted here. Of {formatINR(block.sip_purpose_breakdown.total_monthly)}/mo
              total SIPs, {formatINR(block.sip_purpose_breakdown.goal_monthly)}/mo is earmarked for other goals
              {block.sip_purpose_breakdown.source === 'instrument_heuristic' ? ' (inferred from instrument type)' : ''}.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Excel `Retirement Plan` §3 — the step-up investments table. Projects the
 * client's retirement contributions stepped up each year, future-valued to
 * retirement, and compares the cumulative corpus against the requirement. */
function StepUpTable({ plan, retireAge }: { plan: StepUpPlan; retireAge: number }) {
  const surplus = plan.excess_or_gap >= 0;
  const pct = Math.abs(plan.excess_pct * 100);
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <h3 className="text-sm font-medium text-zinc-700 mb-1">
        Step-up investment plan (Excel-faithful)
      </h3>
      <p className="text-[11px] text-zinc-400 mb-4">
        Mirrors <code className="text-[10px]">Retirement Plan</code> §3 — starting at{' '}
        {formatINR(plan.first_year_monthly_contribution)}/mo and stepping up{' '}
        {(plan.step_up_pct * 100).toFixed(0)}% every year, each contribution is grown to
        retirement at {(plan.rate * 100).toFixed(1)}%. The running total is the corpus the plan
        accumulates by age {retireAge}.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <Big label="Projected corpus at retirement" value={formatINR(plan.projected_corpus_at_retirement, { compact: true })} />
        <Big label="Corpus needed" value={formatINR(plan.corpus_needed, { compact: true })} subtle />
        <Big
          label={surplus ? 'Surplus' : 'Gap'}
          value={`${formatINR(Math.abs(plan.excess_or_gap), { compact: true })} (${surplus ? '+' : '−'}${pct.toFixed(1)}%)`}
          accent={surplus ? 'good' : 'bad'}
        />
      </div>

      <div className="mb-4 rounded-md bg-emerald-50/60 border border-emerald-100 px-3 py-2.5 text-xs flex items-center justify-between">
        <span className="text-zinc-600">
          Required starting SIP to reach the goal (stepped up {(plan.step_up_pct * 100).toFixed(0)}%/yr)
        </span>
        <span className="text-emerald-800 font-semibold tabular-nums">
          {formatINR(plan.required_first_year_monthly)}/mo
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-zinc-500">
            <tr className="text-left border-b border-zinc-100">
              <th className="py-1.5 pr-2">Age</th>
              <th className="py-1.5 pr-2">Yrs to retire</th>
              <th className="text-right pr-2">Annual contribution</th>
              <th className="text-right pr-2">Step-up</th>
              <th className="text-right pr-2">Total</th>
              <th className="text-right pr-2">FV at retirement</th>
              <th className="text-right">Cumulative</th>
            </tr>
          </thead>
          <tbody>
            {plan.rows.map((r, i) => (
              <tr
                key={i}
                className={`border-b border-zinc-100 last:border-0 ${r.is_one_time ? 'bg-zinc-50/60 italic' : ''}`}
              >
                <td className="py-1.5 pr-2 tabular-nums">{r.is_one_time ? '—' : Math.round(r.age)}</td>
                <td className="py-1.5 pr-2 tabular-nums">{r.years_remaining.toFixed(1)}</td>
                <td className="text-right pr-2 tabular-nums">
                  {r.is_one_time ? `${formatINR(r.total_contribution, { compact: true })} (corpus)` : formatINR(r.base_contribution, { compact: true })}
                </td>
                <td className="text-right pr-2 tabular-nums text-zinc-500">
                  {r.step_up_amount ? `+${formatINR(r.step_up_amount, { compact: true })}` : '—'}
                </td>
                <td className="text-right pr-2 tabular-nums">{r.is_one_time ? '—' : formatINR(r.total_contribution, { compact: true })}</td>
                <td className="text-right pr-2 tabular-nums">{formatINR(r.fv_at_retirement, { compact: true })}</td>
                <td className="text-right tabular-nums font-medium">{formatINR(r.cumulative_fv, { compact: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <span className="tabular-nums text-zinc-800">{value}</span>
    </div>
  );
}

function Big({ label, value, subtle, accent }: { label: string; value: string; subtle?: boolean; accent?: 'good' | 'bad' }) {
  const cls = accent === 'bad' ? 'text-rose-700' : accent === 'good' ? 'text-emerald-700' : subtle ? 'text-zinc-700' : 'text-zinc-900';
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50/40 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`text-base font-semibold tabular-nums mt-0.5 ${cls}`}>{value}</div>
    </div>
  );
}
