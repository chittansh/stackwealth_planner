/**
 * India tactical allocator skill.
 * Strategic anchor by risk band → bounded tactical overlay using the signal
 * snapshot from `skills/signals` (real signals on Day 6, fixture today).
 */
import type { AllocationOutput, PlanState } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';
import { getSignals, regimeFromBlocks } from '../signals/index.js';

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

  const snap = getSignals();
  const { score: composite, label: regime_label } = regimeFromBlocks(snap.blocks);

  // Map composite to a desired equity shift (pp) within the band cap.
  const cap = (TACTICAL_BAND[band] ?? TACTICAL_BAND.Moderate).equity;
  let desired = composite >= 4 ? cap : composite >= 1 ? cap * 0.5 : composite >= -1 ? 0 : composite >= -4 ? -cap * 0.5 : -cap;

  // Anti-chase: if valuation is very expensive (-2) but composite is positive, cap shift at 0.
  if (snap.blocks.valuation.score <= -2 && desired > 0) desired = 0;

  // Liquidity safeguard: never reduce cash below strategic.
  const equityShift = Math.round(Math.max(-cap, Math.min(cap, desired)));
  const recommended_allocation = {
    equity: Math.max(0, Math.min(100, strategic.equity + equityShift)),
    debt: Math.max(0, Math.min(100, strategic.debt - equityShift)),
    gold: strategic.gold,
    cash: strategic.cash,
  };

  // Internal equity rotation
  const internalShift = composite > 0 ? 5 : composite < 0 ? -5 : 0;
  const recommended_equity_split = {
    large: Math.max(0, Math.min(100, equitySplit.large + (internalShift < 0 ? -internalShift : 0))),
    mid: Math.max(0, Math.min(100, equitySplit.mid + (internalShift > 0 ? Math.round(internalShift / 2) : 0))),
    small: Math.max(
      0,
      Math.min(
        100,
        equitySplit.small + (internalShift > 0 ? Math.round(internalShift / 2) : Math.round(internalShift / 2)),
      ),
    ),
  };

  // Debt duration stance
  const debt_duration_stance: AllocationOutput['debt_duration_stance'] =
    snap.blocks.macro.score > 0 ? 'extend' : snap.blocks.macro.score < 0 ? 'shorten' : 'neutral';

  // Sector / theme views (light heuristic — dependent on regime)
  const sector_theme_views =
    composite > 0
      ? { overweight: ['Banks', 'Capital Goods', 'Industrials', 'Auto'], underweight: ['Pure defensives'] }
      : composite < 0
      ? { overweight: ['Pharma', 'FMCG', 'Quality private banks'], underweight: ['High-beta cyclicals', 'Speculative small caps'] }
      : { overweight: [], underweight: [] };

  const warnings: string[] = [];
  if (snap.blocks.valuation.score <= -2) warnings.push('Valuation rich — anti-chase active. Equity tilt capped at 0.');
  if (composite === 0) warnings.push('Tactical regime Neutral — recommendation tracks strategic anchor.');

  return {
    investor_risk_band: band,
    strategic_allocation: strategic,
    strategic_equity_split: equitySplit,
    tactical_regime_score: composite,
    tactical_regime_label: regime_label,
    signal_breakdown: snap.blocks,
    recommended_allocation,
    recommended_equity_split,
    debt_duration_stance,
    sector_theme_views,
    rebalancing_actions: rebalanceActions(strategic, recommended_allocation),
    warnings,
  };
}

function rebalanceActions(
  strat: AllocationOutput['strategic_allocation'],
  rec: AllocationOutput['recommended_allocation'],
): string[] {
  const out: string[] = [];
  const eqDelta = rec.equity - strat.equity;
  if (eqDelta > 0) out.push(`Tilt +${eqDelta}pp into equity vs. strategic.`);
  else if (eqDelta < 0) out.push(`Trim ${Math.abs(eqDelta)}pp from equity vs. strategic.`);
  return out;
}
