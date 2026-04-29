'use client';

import { useEffect, useState } from 'react';
import { fetchPlan } from '@/lib/api';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function Headline({ householdId }: { householdId: string }) {
  const [plan, setPlan] = useState<PlanState | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = () => fetchPlan(householdId).then((p) => !cancelled && setPlan(p)).catch(() => undefined);
    tick();
    const id = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [householdId]);

  const horizon = plan?.computed.horizon_years ?? 45;
  const baseline = plan?.computed.headline_amount_at_horizon ?? 0;
  const planB = plan?.scenarios.find((s) => plan.active_scenario_ids.includes(s.id));

  return (
    <div className="flex flex-col">
      <h1 className="text-[34px] font-medium tracking-tight text-zinc-900">
        In {horizon} years you’ll have <span className="text-zinc-900">{formatINR(baseline, { compact: true })}</span>
      </h1>
      {planB && (
        <p className="text-[20px] mt-1 text-[color:var(--color-accent-2)]">
          In {horizon} years you’ll have {formatINR(planB.computed.headline_amount_at_horizon, { compact: true })}
        </p>
      )}
    </div>
  );
}
