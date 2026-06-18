'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';

/**
 * Surplus & SIP feasibility card.
 *
 * Mental model (this is the critical correction over the previous
 * design): SIPs are NOT consumption — they're wealth-building going
 * into the same pool that funds the goals. The card structure
 * reflects that.
 *
 *   Real surplus = Income − Expenses − EMI
 *                  (this is what's available to deploy as SIPs)
 *
 *   Of that surplus:
 *     - some is ALREADY allocated to running SIPs
 *     - some additional may be needed to fully fund goals
 *     - the rest is uninvested cash
 *
 * The earlier version subtracted existing SIPs from surplus AS IF they
 * were expenses, which is wrong: the SIP money is still on the
 * household's balance sheet, just in a different form. RM feedback:
 * "SIPs are not expenses, they are adding to networth."
 */
export function SurplusCard({ plan }: { plan: PlanState }) {
  const s = (plan.computed.cfp?.summary ?? {}) as Record<string, number | boolean | undefined>;

  // Fallback values for households where compute_cfp hasn't run yet.
  const fsi = plan.freedom_score_inputs ?? {};
  const mi = plan.monthly_investments ?? {};
  const incomeFallback = fsi.monthly_income ?? 0;
  const expensesFallback = fsi.monthly_expenses ?? 0;
  const emiFallback = fsi.monthly_emi ?? 0;
  const existingSipFallback =
    (mi.mutual_fund_sip ?? 0) +
    (mi.nps ?? 0) +
    (mi.ppf ?? 0) +
    (mi.rd ?? 0) +
    (mi.direct_equity ?? 0) +
    (mi.other ?? 0);

  const income = (s.monthly_income as number) ?? incomeFallback;
  const expenses = (s.monthly_expenses as number) ?? expensesFallback;
  const emi = (s.monthly_emi as number) ?? emiFallback;
  const existingSip = (s.monthly_existing_sip as number) ?? existingSipFallback;

  // REAL surplus = income − expenses − EMI. SIPs are NOT in this calc.
  const realSurplus = income - expenses - emi;

  const totalRequiredSip = (s.total_required_sip_monthly as number) ?? 0;
  const incrementalRequiredSip = (s.total_incremental_sip_monthly as number) ?? 0;

  // How the existing SIPs sit relative to the real surplus:
  //   - within → there's still uninvested cash on top
  //   - exceeds → household funds the gap from savings/bonus
  const sipsExceedSurplus = existingSip > realSurplus;
  const uninvestedCash = Math.max(0, realSurplus - existingSip);
  const fundedFromSavings = sipsExceedSurplus ? existingSip - realSurplus : 0;

  const hasIncome = income > 0;
  const allGoalsCovered = incrementalRequiredSip <= 0;

  // Bar widths normalised to income so the visualisation reads as
  // "share of every rupee earned that goes here."
  const barFor = (v: number) => (income > 0 ? `${Math.min(100, (v / income) * 100).toFixed(1)}%` : '0%');

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Surplus & SIP feasibility</h3>
        <button
          onClick={() => firePrompt('Walk me through where my monthly surplus goes and whether existing SIPs cover the plan.')}
          className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
          title="Ask about surplus"
        >
          <Plus size={14} />
        </button>
      </header>

      {!hasIncome ? (
        <button
          onClick={() => firePrompt('Tell me your monthly income, expenses, EMI and SIPs so I can compute your surplus.')}
          className="text-left text-[11px] text-zinc-400 hover:text-zinc-700"
        >
          Tell me your monthly income + expenses + SIPs to see surplus →
        </button>
      ) : (
        <>
          {/* ── Headline: REAL surplus (consumption-side) ───────────── */}
          <div
            className={`rounded-lg px-3 py-2 mb-3 border ${
              realSurplus >= 0
                ? 'bg-[var(--color-accent-soft,#eef3eb)] border-[color:var(--color-accent,#5f7d56)]/20'
                : 'bg-rose-50 border-rose-200'
            }`}
          >
            <div className="text-[10px] uppercase tracking-wide text-zinc-500">
              Monthly surplus (income − expenses − EMI)
            </div>
            <div className="flex items-baseline justify-between gap-3 mt-0.5">
              <span
                className={`text-xl font-semibold tabular-nums ${
                  realSurplus >= 0 ? 'text-[color:var(--color-accent,#5f7d56)]' : 'text-rose-700'
                }`}
              >
                {realSurplus < 0 ? '−' : ''}
                {formatINR(Math.abs(realSurplus), { compact: true })}
                <span className="text-xs font-normal text-zinc-500"> /mo</span>
              </span>
              <span className="text-[10px] text-zinc-500 tabular-nums">
                {((realSurplus / (income || 1)) * 100).toFixed(0)}% of income
              </span>
            </div>
            <div className="text-[10px] text-zinc-500 mt-1">This is what&apos;s available to allocate as SIPs.</div>
          </div>

          {/* ── Cashflow waterfall (consumption only) ──────────────── */}
          <div className="flex flex-col gap-1.5 mb-3">
            <Row label="Monthly income" value={income} bar={barFor(income)} tone="positive" />
            <Row label="Living expenses" value={-expenses} bar={barFor(expenses)} tone="negative" />
            {emi > 0 && <Row label="Loan EMIs" value={-emi} bar={barFor(emi)} tone="negative" />}
            <div className="border-t border-dashed border-zinc-200 my-1" />
            <Row
              label="Surplus available for SIPs"
              value={realSurplus}
              tone={realSurplus >= 0 ? 'positive' : 'bad'}
              emphasis
            />
          </div>

          {/* ── SIP allocation (where surplus is going) ─────────────── */}
          {existingSip > 0 && (
            <div className="rounded-md border border-zinc-200 bg-zinc-50/40 p-2.5 mb-2">
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1.5">
                Of your surplus, where it&apos;s going
              </div>
              <div className="flex items-baseline justify-between text-sm py-0.5">
                <span className="text-zinc-700">Existing SIPs (wealth-building)</span>
                <span className="text-zinc-900 tabular-nums">{formatINR(existingSip, { compact: true })}/mo</span>
              </div>
              {uninvestedCash > 0 && !sipsExceedSurplus && (
                <div className="flex items-baseline justify-between text-sm py-0.5">
                  <span className="text-zinc-500">Uninvested cash (sitting idle)</span>
                  <span className="text-zinc-600 tabular-nums">{formatINR(uninvestedCash, { compact: true })}/mo</span>
                </div>
              )}
              {sipsExceedSurplus && (
                <div className="flex items-baseline justify-between text-sm py-0.5">
                  <span className="text-amber-700">Funded from savings / bonuses</span>
                  <span className="text-amber-800 font-medium tabular-nums">
                    {formatINR(fundedFromSavings, { compact: true })}/mo
                  </span>
                </div>
              )}
              {sipsExceedSurplus && (
                <p className="text-[10px] text-zinc-500 mt-1.5 leading-snug">
                  Existing SIPs exceed your monthly surplus by
                  <span className="text-amber-700 font-medium tabular-nums">
                    {' '}
                    {formatINR(fundedFromSavings, { compact: true })}
                  </span>{' '}
                  — the gap is being covered from savings, bonuses, or other unmodelled income.
                </p>
              )}
            </div>
          )}

          {/* ── Goal funding from these SIPs ────────────────────────── */}
          {totalRequiredSip > 0 && (
            <div
              className={`rounded-md border p-2.5 ${
                allGoalsCovered
                  ? 'bg-[var(--color-accent-soft,#eef3eb)] border-[color:var(--color-accent,#5f7d56)]/20'
                  : 'bg-amber-50 border-amber-200'
              }`}
            >
              <div className="flex items-baseline justify-between text-xs mb-1.5">
                <span className="text-zinc-500 uppercase tracking-wide text-[10px]">Goal funding</span>
                <span
                  className={`text-[10px] tabular-nums ${
                    allGoalsCovered ? 'text-[color:var(--color-accent,#5f7d56)]' : 'text-amber-700'
                  }`}
                >
                  {allGoalsCovered ? '✓ all goals funded by existing SIPs' : `${formatINR(incrementalRequiredSip, { compact: true })}/mo more needed`}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-sm py-0.5">
                <span className="text-zinc-700">Required across all goals</span>
                <span className="text-zinc-900 tabular-nums">{formatINR(totalRequiredSip, { compact: true })}/mo</span>
              </div>
              <div className="flex items-baseline justify-between text-sm py-0.5">
                <span className="text-zinc-700">Covered by existing SIPs</span>
                <span className="text-zinc-900 tabular-nums">
                  {formatINR(totalRequiredSip - incrementalRequiredSip, { compact: true })}/mo
                </span>
              </div>
              {!allGoalsCovered && (
                <div className="flex items-baseline justify-between text-sm py-0.5 mt-1 pt-1 border-t border-dashed border-amber-200">
                  <span className="text-amber-800">New commitment needed</span>
                  <span className="text-amber-800 font-medium tabular-nums">
                    {formatINR(incrementalRequiredSip, { compact: true })}/mo
                  </span>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  bar,
  tone,
  emphasis,
}: {
  label: string;
  value: number;
  bar?: string;
  tone: 'positive' | 'negative' | 'muted' | 'bad';
  emphasis?: boolean;
}) {
  const neg = value < 0;
  const barColor =
    tone === 'positive'
      ? 'bg-[color:var(--color-accent,#5f7d56)]/40'
      : tone === 'bad'
      ? 'bg-rose-300/50'
      : tone === 'negative'
      ? 'bg-zinc-400/30'
      : 'bg-zinc-300/30';
  const textColor =
    emphasis && tone === 'positive'
      ? 'text-[color:var(--color-accent,#5f7d56)] font-medium'
      : emphasis && tone === 'bad'
      ? 'text-rose-700 font-medium'
      : 'text-zinc-800';

  return (
    <div className="text-xs">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-zinc-600">{label}</span>
        <span className={`tabular-nums whitespace-nowrap ${textColor}`}>
          {neg ? '−' : ''}
          {formatINR(Math.abs(value), { compact: true })}
        </span>
      </div>
      {bar && (
        <div className="h-1 mt-0.5 rounded-full bg-zinc-100 overflow-hidden">
          <div className={`h-full ${barColor}`} style={{ width: bar }} />
        </div>
      )}
    </div>
  );
}
