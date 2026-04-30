'use client';

import { useEffect, useState } from 'react';
import { fetchPlan } from '@/lib/api';
import type { PlanState } from '@/types/plan-state';

import { Headline } from './Headline';
import { NetWorthChart } from './NetWorthChart';
import { CashFlowTable } from './CashFlowTable';
import { AllocationView } from './AllocationView';
import { TaxView } from './TaxView';
import { GoalsView } from './GoalsView';
import { InsuranceView } from './InsuranceView';
import { PlanBlocks } from './PlanBlocks';
import { Scenarios } from './Scenarios';
import { ScenarioChips } from './ScenarioChips';
import { RiskBanner } from './RiskBanner';

export function CanvasRouter({
  householdId,
  view,
  horizon,
}: {
  householdId: string;
  view: 'net-worth' | 'cash-flow' | 'allocation' | 'goals' | 'insurance' | 'tax';
  horizon: number;
}) {
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

  return (
    <div className="flex flex-col">
      <Headline householdId={householdId} plan={plan} />
      <RiskBanner plan={plan} />

      {view === 'net-worth' && (
        <>
          <div className="mt-6">
            <NetWorthChart householdId={householdId} plan={plan} />
            <ScenarioChips plan={plan} />
          </div>
        </>
      )}
      {view === 'cash-flow' && (
        <div className="mt-6">
          <CashFlowTable plan={plan} />
        </div>
      )}
      {view === 'allocation' && (
        <div className="mt-6">
          <AllocationView plan={plan} />
        </div>
      )}
      {view === 'tax' && (
        <div className="mt-6">
          <TaxView householdId={householdId} plan={plan} />
        </div>
      )}
      {view === 'goals' && (
        <div className="mt-6">
          <GoalsView plan={plan} />
        </div>
      )}
      {view === 'insurance' && (
        <div className="mt-6">
          <InsuranceView plan={plan} />
        </div>
      )}

      <div className="mt-10">
        <Scenarios householdId={householdId} plan={plan} />
      </div>
      <div className="mt-8">
        <PlanBlocks plan={plan} />
      </div>
    </div>
  );
}
