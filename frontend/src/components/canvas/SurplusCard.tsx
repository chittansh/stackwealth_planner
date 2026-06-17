'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';

/**
 * Surplus card — sits after the Expenses card in the net-worth layout.
 *
 * Shows what's left over each month after living + EMI + existing SIPs,
 * and whether that surplus is large enough to fund the goals the CFP
 * engine says the household needs. The "is the required SIP realistic?"
 * gut-check we used to handwave (engine emits ₹2.85L/mo SIP for someone
 * earning ₹1.33L/mo) is now first-class state on plan.computed.cfp.summary.
 */
export function SurplusCard({ plan }: { plan: PlanState }) {
  const s = (plan.computed.cfp?.summary ?? {}) as Record<string, number | boolean | undefined>;

  // Fallback: when CFP hasn't run yet, derive from raw FSI so the card
  // isn't empty on a fresh household.
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
    (mi.direct_equity ?? 0);

  const income = (s.monthly_income as number) ?? incomeFallback;
  const expenses = (s.monthly_expenses as number) ?? expensesFallback;
  const emi = (s.monthly_emi as number) ?? emiFallback;
  const existingSip = (s.monthly_existing_sip as number) ?? existingSipFallback;
  const surplusAfterExisting =
    (s.monthly_surplus_after_existing_sip as number) ?? income - expenses - emi - existingSip;
  const totalRequiredSip = (s.total_required_sip_monthly as number) ?? 0;
  const incrementalRequiredSip = (s.total_incremental_sip_monthly as number) ?? 0;
  const affordableNewSip = (s.affordable_new_sip_monthly as number) ?? Math.max(0, surplusAfterExisting);
  const shortfall = (s.sip_surplus_shortfall_monthly as number) ?? Math.max(0, incrementalRequiredSip - affordableNewSip);
  const rationFactor = (s.sip_ration_factor as number) ?? 1;
  const isAffordable = (s.is_plan_affordable as boolean) ?? shortfall <= 0;

  const hasIncome = income > 0;

  // Bar widths for the inflow/outflow visualisation. Normalised against
  // income so an EMI-heavy household sees a wider EMI bar than a
  // similarly-sized expenses block.
  const barFor = (v: number) => (income > 0 ? `${Math.min(100, (v / income) * 100).toFixed(1)}%` : '0%');

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Surplus & SIP feasibility</h3>
        <button
          onClick={() => firePrompt('Walk me through where my monthly surplus is going and whether it covers my goal SIPs.')}
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
          {/* Headline surplus tile */}
          <div className={`rounded-lg px-3 py-2 mb-3 border ${
            surplusAfterExisting >= 0
              ? 'bg-[var(--color-accent-soft,#eef3eb)] border-[color:var(--color-accent,#5f7d56)]/20'
              : 'bg-rose-50 border-rose-200'
          }`}>
            <div className="text-[10px] uppercase tracking-wide text-zinc-500">
              Surplus after expenses + EMI + existing SIPs
            </div>
            <div className="flex items-baseline justify-between gap-3 mt-0.5">
              <span className={`text-xl font-semibold tabular-nums ${
                surplusAfterExisting >= 0 ? 'text-[color:var(--color-accent,#5f7d56)]' : 'text-rose-700'
              }`}>
                {surplusAfterExisting < 0 ? '−' : ''}
                {formatINR(Math.abs(surplusAfterExisting), { compact: true })}
                <span className="text-xs font-normal text-zinc-500"> /mo</span>
              </span>
              <span className="text-[10px] text-zinc-500 tabular-nums">
                {((surplusAfterExisting / (income || 1)) * 100).toFixed(0)}% of income
              </span>
            </div>
          </div>

          {/* Cashflow waterfall */}
          <div className="flex flex-col gap-1.5 mb-3">
            <Row label="Monthly income" value={income} bar={barFor(income)} tone="positive" />
            <Row label="Living expenses" value={-expenses} bar={barFor(expenses)} tone="negative" />
            {emi > 0 && <Row label="Loan EMIs" value={-emi} bar={barFor(emi)} tone="negative" />}
            {existingSip > 0 && (
              <Row label="Existing SIPs" value={-existingSip} bar={barFor(existingSip)} tone="muted" hint="going to wealth, not consumption" />
            )}
            <div className="border-t border-dashed border-zinc-200 my-1" />
            <Row label="Available for new SIPs" value={Math.max(0, affordableNewSip)} tone="positive" emphasis />
          </div>

          {/* SIP feasibility check */}
          {incrementalRequiredSip > 0 && (
            <div className={`rounded-md border p-2.5 ${
              isAffordable ? 'bg-zinc-50 border-zinc-200' : 'bg-amber-50 border-amber-200'
            }`}>
              <div className="flex items-baseline justify-between text-xs mb-1">
                <span className="text-zinc-500 uppercase tracking-wide text-[10px]">
                  Goal SIPs — required vs feasible
                </span>
                <span className={`text-[10px] tabular-nums ${isAffordable ? 'text-[color:var(--color-accent,#5f7d56)]' : 'text-amber-700'}`}>
                  {isAffordable ? '✓ affordable' : `${(rationFactor * 100).toFixed(0)}% of goals fundable`}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-zinc-700">Required incremental SIP</span>
                <span className="text-zinc-900 tabular-nums">{formatINR(incrementalRequiredSip, { compact: true })}/mo</span>
              </div>
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-zinc-700">Surplus you can spare</span>
                <span className="text-zinc-900 tabular-nums">{formatINR(affordableNewSip, { compact: true })}/mo</span>
              </div>
              {!isAffordable && shortfall > 0 && (
                <div className="mt-2 pt-2 border-t border-dashed border-amber-200 text-xs">
                  <div className="flex items-baseline justify-between">
                    <span className="text-amber-800">Shortfall</span>
                    <span className="text-amber-800 font-medium tabular-nums">−{formatINR(shortfall, { compact: true })}/mo</span>
                  </div>
                  <p className="text-[10px] text-amber-700 mt-1 leading-snug">
                    Required SIPs exceed available surplus. Either extend goal horizons, reduce target amounts,
                    raise income, or accept that goals get partially funded at ~{(rationFactor * 100).toFixed(0)}%
                    of plan.
                  </p>
                </div>
              )}
              {totalRequiredSip !== incrementalRequiredSip && (
                <div className="mt-1 text-[10px] text-zinc-500">
                  Total goal SIPs at full plan: {formatINR(totalRequiredSip, { compact: true })}/mo
                  &nbsp;·&nbsp; existing SIPs already covering {formatINR(totalRequiredSip - incrementalRequiredSip, { compact: true })}/mo of that.
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
  hint,
  emphasis,
}: {
  label: string;
  value: number;
  bar?: string;
  tone: 'positive' | 'negative' | 'muted';
  hint?: string;
  emphasis?: boolean;
}) {
  const neg = value < 0;
  const barColor =
    tone === 'positive'
      ? 'bg-[color:var(--color-accent,#5f7d56)]/40'
      : tone === 'negative'
      ? 'bg-zinc-400/30'
      : 'bg-zinc-300/30';
  const textColor =
    tone === 'positive' && emphasis
      ? 'text-[color:var(--color-accent,#5f7d56)] font-medium'
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
      {hint && <div className="text-[10px] text-zinc-400 mt-0.5">{hint}</div>}
    </div>
  );
}
