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
  const inFlightRef = useRef(false);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refetch = useCallback(() => {
    if (inFlightRef.current) return;   // collapse overlapping fetches
    inFlightRef.current = true;
    fetchPlan(householdId)
      .then((p) => {
        if (!cancelledRef.current) setPlan(p);
      })
      .catch(() => undefined)
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [householdId]);

  // Debounced refetch — coalesces the burst of `sw:plan-changed` events that
  // a single agent turn fires (one per tool_result + one on done) into a
  // single network round-trip ~250ms after the LAST event in the burst.
  const debouncedRefetch = useCallback(() => {
    if (pendingTimerRef.current !== null) clearTimeout(pendingTimerRef.current);
    pendingTimerRef.current = setTimeout(() => {
      pendingTimerRef.current = null;
      refetch();
    }, 250);
  }, [refetch]);

  useEffect(() => {
    cancelledRef.current = false;
    refetch();
    // Background safety-net poll only — catches agent-driven mutations that
    // didn't fire `sw:plan-changed`. Aggressive polling (was 2s) thrashed
    // the right panel; 30s is plenty since explicit mutation events drive
    // the immediate-refresh path.
    const id = setInterval(refetch, 30_000);
    window.addEventListener('sw:plan-changed', debouncedRefetch);
    return () => {
      cancelledRef.current = true;
      clearInterval(id);
      if (pendingTimerRef.current !== null) clearTimeout(pendingTimerRef.current);
      window.removeEventListener('sw:plan-changed', debouncedRefetch);
    };
  }, [householdId, refetch, debouncedRefetch]);

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
