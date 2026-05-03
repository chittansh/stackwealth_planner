'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';

const ADD_PROMPT = 'Help me add a recurring monthly expense.';

const FIELDS: { key: keyof NonNullable<PlanState['monthly_expenses']>; label: string; meta?: string }[] = [
  { key: 'rent_or_emi', label: 'Rent / EMI', meta: 'inflation only' },
  { key: 'household_expenses', label: 'Household', meta: 'inflation only' },
  { key: 'groceries', label: 'Groceries', meta: 'inflation only' },
  { key: 'utilities', label: 'Utilities' },
  { key: 'school_fees', label: 'School fees', meta: '8%/yr' },
  { key: 'insurance_premium', label: 'Insurance' },
  { key: 'medical', label: 'Medical' },
  { key: 'travel_or_lifestyle', label: 'Travel / Lifestyle' },
  { key: 'other_emis', label: 'Other EMIs' },
];

export function ExpensesCard({ plan }: { plan: PlanState }) {
  const e = plan.monthly_expenses ?? {};
  const rows = FIELDS.map((f) => ({ ...f, amount: ((e[f.key] as number | null | undefined) ?? 0) * 12 })).filter(
    (r) => r.amount > 0,
  );

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Expenses</h3>
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
          {rows.map((r) => (
            <li key={r.key as string} className="flex flex-col">
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
