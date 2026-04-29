'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function OtherEventsCard({ plan }: { plan: PlanState }) {
  const goals = plan.financial_goals.filter((g) => g.target_year);
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Other Events</h3>
        <button className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:bg-zinc-50">
          <Plus size={14} />
        </button>
      </header>
      {goals.length === 0 ? (
        <p className="text-xs text-zinc-400">No items yet — type a request or click +</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {goals.map((g) => (
            <li key={g.id} className="flex flex-col">
              <div className="flex justify-between text-sm">
                <span className="text-zinc-800">{g.goal_name}</span>
                <span className="tabular-nums">{formatINR(g.target_amount ?? g.today_cost ?? 0, { compact: true })}</span>
              </div>
              <span className="text-[11px] text-zinc-400">{g.target_year}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
