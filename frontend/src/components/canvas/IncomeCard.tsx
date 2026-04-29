'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function IncomeCard({ plan }: { plan: PlanState }) {
  const rows: { label: string; amount?: number | null; meta?: string }[] = [
    { label: `${plan.personal_details.full_name ?? 'Client'} Salary`, amount: (plan.income_details.client_salary_in_hand ?? 0) * 12, meta: 'inflation only · Active' },
    { label: 'Spouse Salary', amount: (plan.income_details.spouse_salary_in_hand ?? 0) * 12, meta: 'inflation only · Active' },
    { label: 'Rental income', amount: (plan.income_details.client_rental_income ?? 0) * 12, meta: '6%/yr' },
    { label: 'Other income', amount: (plan.income_details.client_other_income ?? 0) * 12, meta: '' },
  ].filter((r) => (r.amount ?? 0) > 0);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Income</h3>
        <button className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:bg-zinc-50">
          <Plus size={14} />
        </button>
      </header>
      {rows.length === 0 ? (
        <p className="text-xs text-zinc-400">No items yet — type a request or click +</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((r, i) => (
            <li key={i} className="flex flex-col">
              <div className="flex justify-between text-sm">
                <span className="text-zinc-800">{r.label}</span>
                <span className="tabular-nums">{formatINR(r.amount ?? 0, { compact: true })}/yr</span>
              </div>
              {r.meta && <span className="text-[11px] text-zinc-400">{r.meta}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
