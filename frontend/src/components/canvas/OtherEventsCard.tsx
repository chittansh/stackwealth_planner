'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';

const ADD_PROMPT = 'I want to add a financial goal — walk me through it.';

export function OtherEventsCard({ plan }: { plan: PlanState }) {
  const goals = plan.financial_goals.filter((g) => g.target_year);
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Other Events</h3>
        <button
          onClick={() => firePrompt(ADD_PROMPT)}
          className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
          title="Add via chat"
        >
          <Plus size={14} />
        </button>
      </header>
      {goals.length === 0 ? (
        <button onClick={() => firePrompt(ADD_PROMPT)} className="text-left text-[11px] text-zinc-400 hover:text-zinc-700">
          No items yet — type a request or click + →
        </button>
      ) : (
        <ul className="flex flex-col gap-2">
          {goals
            .sort((a, b) => (a.target_year ?? 0) - (b.target_year ?? 0))
            .map((g) => (
              <li key={g.id} className="flex flex-col">
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="text-zinc-800 truncate">{g.goal_name}</span>
                  <span className="tabular-nums text-zinc-900 whitespace-nowrap shrink-0">
                    {formatINR(g.target_amount ?? g.today_cost ?? 0, { compact: true })}
                  </span>
                </div>
                <span className="text-[10px] text-zinc-400 capitalize">
                  {g.target_year} · {g.kind.replace(/_/g, ' ')}
                </span>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
