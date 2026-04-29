'use client';

import { useEffect, useState } from 'react';
import { fetchPlan } from '@/lib/api';
import type { PlanState } from '@/types/plan-state';
import { CurrentNetWorthCard } from './CurrentNetWorthCard';
import { IncomeCard } from './IncomeCard';
import { ExpensesCard } from './ExpensesCard';
import { OtherEventsCard } from './OtherEventsCard';
import { AssumptionsCard } from './AssumptionsCard';

export function PlanBlocks({ householdId }: { householdId: string }) {
  const [plan, setPlan] = useState<PlanState | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = () => fetchPlan(householdId).then((p) => !cancelled && setPlan(p)).catch(() => undefined);
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [householdId]);

  if (!plan) return null;

  return (
    <div className="flex flex-col gap-8">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        <CurrentNetWorthCard plan={plan} />
        <IncomeCard plan={plan} />
        <ExpensesCard plan={plan} />
        <OtherEventsCard plan={plan} />
      </div>
      <AssumptionsCard plan={plan} />
    </div>
  );
}
