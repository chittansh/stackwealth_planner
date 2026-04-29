/**
 * India tactical allocator skill.
 * Strategic mapping by risk band → bounded tactical overlay (6 signal blocks).
 * Day 3 hardcodes signals to "Neutral" (zeros). Day 6 swaps in cached real signals.
 */
import type { AllocationOutput, PlanState } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';

const STRATEGIC: Record<string, AllocationOutput['strategic_allocation']> = {
  Conservative: { equity: 20, debt: 60, gold: 15, cash: 5 },
  'Moderately Conservative': { equity: 35, debt: 45, gold: 15, cash: 5 },
  Moderate: { equity: 50, debt: 35, gold: 10, cash: 5 },
  'Moderately Aggressive': { equity: 65, debt: 25, gold: 7, cash: 3 },
  Aggressive: { equity: 80, debt: 12, gold: 5, cash: 3 },
};

const EQUITY_SPLIT: Record<string, AllocationOutput['strategic_equity_split']> = {
  Conservative: { large: 85, mid: 10, small: 5 },
  'Moderately Conservative': { large: 75, mid: 15, small: 10 },
  Moderate: { large: 65, mid: 20, small: 15 },
  'Moderately Aggressive': { large: 55, mid: 25, small: 20 },
  Aggressive: { large: 45, mid: 30, small: 25 },
};

const TACTICAL_BAND: Record<string, { equity: number; gold: number; cash: number }> = {
  Conservative: { equity: 4, gold: 3, cash: 3 },
  'Moderately Conservative': { equity: 6, gold: 4, cash: 3 },
  Moderate: { equity: 8, gold: 5, cash: 4 },
  'Moderately Aggressive': { equity: 10, gold: 5, cash: 5 },
  Aggressive: { equity: 12, gold: 5, cash: 5 },
};

export async function recommend(args: { household_id: string }): Promise<AllocationOutput | { error: string }> {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  if (!plan.computed.risk_profile?.recommended_score) return { error: 'risk_gate_required' };
  return computeAllocation(plan);
}

export function computeAllocation(plan: PlanState): AllocationOutput {
  const band = plan.computed.risk_profile!.recommended_profile;
  const strategic = STRATEGIC[band] ?? STRATEGIC.Moderate;
  const equitySplit = EQUITY_SPLIT[band] ?? EQUITY_SPLIT.Moderate;

  // Day 3: signals hardcoded to Neutral. Day 6 swaps in `signal_snapshots`.
  const signal_breakdown = {
    valuation: { score: 0, reason: 'Neutral (no live signal feed wired yet)' },
    trend: { score: 0, reason: 'Neutral' },
    breadth: { score: 0, reason: 'Neutral' },
    flows: { score: 0, reason: 'Neutral' },
    macro: { score: 0, reason: 'Neutral' },
    external: { score: 0, reason: 'Neutral' },
  };
  const composite = Object.values(signal_breakdown).reduce((a, s) => a + s.score, 0);
  const regime_label =
    composite >= 4 ? 'Risk-On' :
    composite >= 1 ? 'Mild Risk-On' :
    composite >= -1 ? 'Neutral' :
    composite >= -4 ? 'Mild Defensive' : 'Defensive';

  const recommended_allocation = { ...strategic };
  const recommended_equity_split = { ...equitySplit };
  const debt_duration_stance: AllocationOutput['debt_duration_stance'] = 'neutral';

  return {
    investor_risk_band: band,
    strategic_allocation: strategic,
    strategic_equity_split: equitySplit,
    tactical_regime_score: composite,
    tactical_regime_label: regime_label,
    signal_breakdown,
    recommended_allocation,
    recommended_equity_split,
    debt_duration_stance,
    sector_theme_views: { overweight: [], underweight: [] },
    rebalancing_actions: [],
    warnings: composite === 0 ? ['Tactical signals not yet wired — recommendation equals strategic anchor.'] : [],
  };
}

// referenced by Day 4 work — bounded shift helper (kept exported for tests)
export function applyBoundedShift(
  base: AllocationOutput['strategic_allocation'],
  desiredEquityDelta: number,
  band: string,
): AllocationOutput['strategic_allocation'] {
  const cap = (TACTICAL_BAND[band] ?? TACTICAL_BAND.Moderate).equity;
  const shift = Math.max(-cap, Math.min(cap, desiredEquityDelta));
  return {
    equity: Math.max(0, Math.min(100, base.equity + shift)),
    debt: Math.max(0, Math.min(100, base.debt - shift)),
    gold: base.gold,
    cash: base.cash,
  };
}
