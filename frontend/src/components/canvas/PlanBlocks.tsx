'use client';

import type { PlanState } from '@/types/plan-state';
import { CurrentNetWorthCard } from './CurrentNetWorthCard';
import { IncomeCard } from './IncomeCard';
import { ExpensesCard } from './ExpensesCard';
import { OtherEventsCard } from './OtherEventsCard';
import { SurplusCard } from './SurplusCard';
import { AssumptionsCard } from './AssumptionsCard';

export function PlanBlocks({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  return (
    <div className="flex flex-col gap-8">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        <CurrentNetWorthCard plan={plan} />
        <IncomeCard plan={plan} />
        <ExpensesCard plan={plan} />
        <OtherEventsCard plan={plan} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SurplusCard plan={plan} />
      </div>
      <AssumptionsCard plan={plan} />
    </div>
  );
}
