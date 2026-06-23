'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

/**
 * Monthly cash-flow summary for the Net Worth page: total income, expenses
 * (living + EMI), savings (the gross monthly surplus), and the investable
 * surplus — with a source / outflow breakdown. Reads `plan.computed.cfp.summary`
 * (authoritative), falling back to freedom-score inputs before the CFP runs.
 */
export function CashSummaryCard({ plan }: { plan: PlanState }) {
  const s = (plan.computed.cfp?.summary ?? {}) as Record<string, number | undefined>;
  const fsi = plan.freedom_score_inputs ?? {};
  const inc = plan.income_details ?? {};

  const income = s.monthly_income ?? fsi.monthly_income ?? 0;
  const expenses = s.monthly_expenses ?? fsi.monthly_expenses ?? 0;
  const emi = s.monthly_emi ?? fsi.monthly_emi ?? 0;
  const existingSip = s.monthly_existing_sip ?? 0;
  const savings = income - expenses - emi; // gross monthly surplus

  // Investable surplus = engine value (income − essentials − EMI − insurance −
  // emergency-fund build SIP) when available, else the gross surplus.
  const scenInvestable = (plan.computed.scenarios_v2 as { surplus?: { investable_surplus?: number } } | undefined)
    ?.surplus?.investable_surplus;
  const investable = scenInvestable ?? savings;

  const incomeRows = [
    { label: 'Salary', amount: (inc.client_salary_in_hand ?? 0) + (inc.spouse_salary_in_hand ?? 0) },
    { label: 'Business', amount: (inc.client_business_income ?? 0) + (inc.spouse_business_income ?? 0) },
    { label: 'Rental', amount: (inc.client_rental_income ?? 0) + (inc.spouse_rental_income ?? 0) },
    { label: 'Other', amount: (inc.client_other_income ?? 0) + (inc.spouse_other_income ?? 0) },
  ].filter((r) => r.amount > 0);

  const outflowRows = [
    { label: 'Living expenses', amount: expenses },
    { label: 'Loan EMI', amount: emi },
    { label: 'Current investments (SIPs)', amount: existingSip },
  ].filter((r) => r.amount > 0);

  const stats = [
    { label: 'Monthly income', value: income, tone: 'good' as const },
    { label: 'Expenses + EMI', value: expenses + emi, tone: 'neutral' as const },
    { label: 'Savings (surplus)', value: savings, tone: savings >= 0 ? ('good' as const) : ('bad' as const) },
    { label: 'Investable surplus', value: investable, tone: investable >= 0 ? ('good' as const) : ('bad' as const) },
  ];

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <div className="mb-3">
        <h3 className="text-sm font-medium text-zinc-800">Monthly cash flow</h3>
        <p className="text-[11px] text-zinc-500 mt-0.5">
          What comes in, what goes out, and what&apos;s left to invest each month.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {stats.map((st) => (
          <div key={st.label} className="rounded-lg border border-zinc-200 bg-zinc-50/40 px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wide text-zinc-400">{st.label}</div>
            <div
              className={`text-lg font-semibold tabular-nums mt-0.5 ${
                st.tone === 'good' ? 'text-[color:var(--color-accent,#5f7d56)]' : st.tone === 'bad' ? 'text-rose-700' : 'text-zinc-800'
              }`}
            >
              {formatINR(st.value)}/mo
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Income sources</div>
          {incomeRows.length ? (
            incomeRows.map((r) => <Row key={r.label} label={r.label} amount={r.amount} />)
          ) : (
            <Row label="Total income" amount={income} />
          )}
          <Row label="Total income" amount={income} strong />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Where it goes</div>
          {outflowRows.map((r) => (
            <Row key={r.label} label={r.label} amount={r.amount} />
          ))}
          <Row label="Free cash after SIPs" amount={Math.max(0, savings - existingSip)} strong />
        </div>
      </div>
    </div>
  );
}

function Row({ label, amount, strong }: { label: string; amount: number; strong?: boolean }) {
  return (
    <div className={`flex justify-between text-xs py-1 border-b border-dashed border-zinc-100 last:border-0 ${strong ? 'font-medium text-zinc-900' : 'text-zinc-600'}`}>
      <span>{label}</span>
      <span className="tabular-nums">{formatINR(amount)}/mo</span>
    </div>
  );
}
