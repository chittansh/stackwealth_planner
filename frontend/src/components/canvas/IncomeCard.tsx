'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';

const ADD_PROMPT = 'I want to add a new income source — walk me through it.';

export function IncomeCard({ plan }: { plan: PlanState }) {
  const inc = plan.income_details ?? {};
  const firstName = plan.personal_details.full_name?.split(/[ &]/)[0] ?? 'You';
  let rows: { label: string; amount: number; meta: string }[] = [
    { label: `${firstName} · Salary`, amount: (inc.client_salary_in_hand ?? 0) * 12, meta: 'inflation only · Active' },
    { label: 'Spouse · Salary', amount: (inc.spouse_salary_in_hand ?? 0) * 12, meta: 'inflation only · Active' },
    { label: 'You · Business', amount: (inc.client_business_income ?? 0) * 12, meta: '' },
    { label: 'Spouse · Business', amount: (inc.spouse_business_income ?? 0) * 12, meta: '' },
    { label: 'Rental income', amount: ((inc.client_rental_income ?? 0) + (inc.spouse_rental_income ?? 0)) * 12, meta: '6%/yr' },
    { label: 'Other income', amount: ((inc.client_other_income ?? 0) + (inc.spouse_other_income ?? 0)) * 12, meta: '' },
  ].filter((r) => r.amount > 0);

  // Defensive fallback: when the agent has only set `freedom_score_inputs
  // .monthly_income` (the aggregate) and skipped writing the breakdown,
  // surface a single aggregate row so the card isn't misleadingly empty.
  // The chart and freedom score read from FSI anyway, so the data IS
  // there — just not split across categories yet.
  if (rows.length === 0) {
    const aggMonthly = plan.freedom_score_inputs.monthly_income ?? 0;
    if (aggMonthly > 0) {
      rows = [
        {
          label: `${firstName} · Take-home`,
          amount: aggMonthly * 12,
          meta: 'inflation only · breakdown unset',
        },
      ];
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Income</h3>
        <button
          onClick={() => firePrompt(ADD_PROMPT)}
          className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
          title="Add via chat"
        >
          <Plus size={14} />
        </button>
      </header>
      {rows.length === 0 ? (
        <button onClick={() => firePrompt(ADD_PROMPT)} className="text-left text-[11px] text-zinc-400 hover:text-zinc-700">
          No items yet — type a request or click + →
        </button>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((r, i) => (
            <li key={i} className="flex flex-col">
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="text-zinc-800 truncate">{r.label}</span>
                <span className="tabular-nums text-zinc-900 whitespace-nowrap shrink-0">
                  {formatINR(r.amount, { compact: true })}
                  <span className="text-zinc-400">/yr</span>
                </span>
              </div>
              {r.meta && <span className="text-[10px] text-zinc-400">{r.meta}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
