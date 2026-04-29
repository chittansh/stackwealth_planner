/**
 * Tax harvesting skill — TS port of StackWealth_Tax_Harvesting_Calculator_v3.
 * Day 4 fills Gain / Loss / Combined / Fee-vs-Value sub-views.
 */
import type { TaxView } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';

const LTCG_HEADROOM_INR = 125_000; // FY24 regime — ₹1.25L exempt LTCG / FY

export async function harvest(args: { household_id: string }): Promise<TaxView | { error: string }> {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  if (!plan.computed.risk_profile?.recommended_score) return { error: 'risk_gate_required' };

  // Skeleton — Day 4 wires per-holding cost basis and computes real harvest suggestions.
  const realized_ltcg_fy = 0;
  const realized_stcg_fy = 0;
  return {
    ltcg_headroom_remaining: Math.max(0, LTCG_HEADROOM_INR - realized_ltcg_fy),
    realized_ltcg_fy,
    realized_stcg_fy,
    gain_harvest_suggestions: [],
    loss_harvest_suggestions: [],
    fee_vs_value_warnings: [],
    net_post_tax_delta: 0,
  };
}
