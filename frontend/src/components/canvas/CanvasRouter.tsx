'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
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
  void horizon; // sourced from server (plan.computed.horizon_years)
  const [plan, setPlan] = useState<PlanState | null>(null);
  const cancelledRef = useRef(false);

  const refetch = useCallback(() => {
    fetchPlan(householdId)
      .then((p) => !cancelledRef.current && setPlan(p))
      .catch(() => undefined);
  }, [householdId]);

  useEffect(() => {
    cancelledRef.current = false;
    refetch();
    // Slow background poll as a safety net (catches agent-driven mutations
    // that didn't fire sw:plan-changed for any reason).
    const id = setInterval(refetch, 2000);
    // Instant refresh on any explicit mutation event.
    const onChanged = () => refetch();
    window.addEventListener('sw:plan-changed', onChanged);
    return () => {
      cancelledRef.current = true;
      clearInterval(id);
      window.removeEventListener('sw:plan-changed', onChanged);
    };
  }, [householdId, refetch]);

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
