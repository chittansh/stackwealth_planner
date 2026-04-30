'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { NewsStrip } from './NewsStrip';

export function Headline({ householdId, plan }: { householdId: string; plan: PlanState | null }) {
  const horizon = plan?.computed.horizon_years ?? 45;
  const baseline = plan?.computed.headline_amount_at_horizon ?? 0;
  const planB = plan?.scenarios.find((s) => plan.active_scenario_ids.includes(s.id));
  const fs = plan?.computed.freedom_score?.final_score;

  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex flex-col min-w-0">
        <h1 className="text-[34px] font-medium tracking-tight text-zinc-900 leading-tight">
          In {horizon} years you’ll have <span className="text-zinc-900">{formatINR(baseline, { compact: true })}</span>
        </h1>
        {planB && (
          <p className="text-[20px] mt-1 text-[color:var(--color-accent-2)]">
            In {horizon} years you’ll have {formatINR(planB.computed.headline_amount_at_horizon, { compact: true })}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0 mt-2">
        {typeof fs === 'number' && (
          <span className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-600">
            <span className="text-zinc-400">Freedom</span>{' '}
            <span className="text-zinc-900 tabular-nums">{fs.toFixed(0)}</span>
            <span className="text-zinc-400">/100</span>
          </span>
        )}
        <NewsStrip householdId={householdId} />
      </div>
    </div>
  );
}
