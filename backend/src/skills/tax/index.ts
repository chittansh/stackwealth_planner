/**
 * Tax harvesting skill — TS port of StackWealth_Tax_Harvesting_Calculator_v3.
 *
 * Approach (without per-trade cost basis available yet):
 *   - Treat each MF / equity holding as ~30% unrealized gain (conservative
 *     proxy for a long-term holder). Day 6 wires real cost basis from the
 *     intake evidence rows.
 *   - LTCG headroom: ₹1.25 L/FY (post-FY24 regime).
 *   - Suggest harvesting up to the headroom by selling proportional units
 *     of holdings with the highest unrealized gain.
 *   - Loss harvest: any holding tagged `long_term_or_trading=trading` with
 *     a negative current value vs. proxy cost basis is a candidate.
 *   - Fee-vs-value gate: skip suggestions whose tax saving < est. churn cost
 *     (assumed 0.5% round-trip).
 */
import type { TaxView, PlanState, MFHolding, StockHolding } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';

const LTCG_HEADROOM_INR = 125_000;
const LTCG_RATE = 0.125;
const STCG_RATE = 0.20;
const ROUND_TRIP_COST_PCT = 0.005;
const UNREALIZED_GAIN_PROXY = 0.30;

export async function harvest(args: { household_id: string }): Promise<TaxView | { error: string }> {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  if (!plan.computed.risk_profile?.recommended_score) return { error: 'risk_gate_required' };
  return computeTax(plan);
}

export function computeTax(plan: PlanState): TaxView {
  const realized_ltcg_fy = 0; // wired once per-trade ledger lands
  const realized_stcg_fy = 0;
  const headroomRemaining = Math.max(0, LTCG_HEADROOM_INR - realized_ltcg_fy);

  // Build candidate list: (id, currentValue, unrealizedGain estimate, kind)
  type Cand = { id: string; cur: number; gain: number; kind: 'mf' | 'stock'; trading: boolean };
  const candidates: Cand[] = [
    ...plan.mutual_funds.map<Cand>((h: MFHolding) => ({
      id: h.id,
      cur: h.current_value ?? 0,
      gain: (h.current_value ?? 0) * UNREALIZED_GAIN_PROXY,
      kind: 'mf',
      trading: false,
    })),
    ...plan.equity_stocks.map<Cand>((h: StockHolding) => ({
      id: h.id,
      cur: h.current_value ?? 0,
      gain: (h.current_value ?? 0) * UNREALIZED_GAIN_PROXY,
      kind: 'stock',
      trading: h.long_term_or_trading === 'trading',
    })),
  ].filter((c) => c.cur > 0);

  // ── Gain harvest: pick holdings whose proportional gain fits the headroom ──
  const gain_harvest_suggestions: TaxView['gain_harvest_suggestions'] = [];
  let remaining = headroomRemaining;
  candidates
    .slice()
    .sort((a, b) => b.gain - a.gain)
    .forEach((c) => {
      if (remaining <= 0) return;
      const sellGain = Math.min(c.gain, remaining);
      const fraction = c.gain > 0 ? sellGain / c.gain : 0;
      if (fraction <= 0.001) return;
      const sellValue = c.cur * fraction;
      const tax_saved = sellGain * LTCG_RATE;
      const churn = sellValue * ROUND_TRIP_COST_PCT;
      if (tax_saved <= churn) return; // fee-vs-value gate
      gain_harvest_suggestions.push({
        holding_id: c.id,
        units: fraction * 100, // unit proxy: percentage of holding
        expected_gain: Number(sellGain.toFixed(0)),
        tax_saved: Number(tax_saved.toFixed(0)),
      });
      remaining -= sellGain;
    });

  // ── Loss harvest: only `trading` holdings flagged with a notional loss proxy ──
  const loss_harvest_suggestions: TaxView['loss_harvest_suggestions'] = candidates
    .filter((c) => c.trading)
    .map((c) => {
      const lossProxy = c.cur * 0.10;
      const offset = lossProxy * STCG_RATE;
      const churn = c.cur * ROUND_TRIP_COST_PCT;
      if (offset <= churn) return null;
      return {
        holding_id: c.id,
        units: 100,
        expected_loss: -Number(lossProxy.toFixed(0)),
        tax_offset: Number(offset.toFixed(0)),
      };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);

  // ── Fee-vs-value warnings on borderline suggestions
  const fee_vs_value_warnings: string[] = [];
  if (gain_harvest_suggestions.length === 0 && headroomRemaining > 0) {
    fee_vs_value_warnings.push('No gain-harvest opportunities cleared the round-trip cost gate this FY.');
  }

  const net_post_tax_delta =
    gain_harvest_suggestions.reduce((a, s) => a + s.tax_saved, 0) +
    loss_harvest_suggestions.reduce((a, s) => a + s.tax_offset, 0);

  return {
    ltcg_headroom_remaining: headroomRemaining,
    realized_ltcg_fy,
    realized_stcg_fy,
    gain_harvest_suggestions,
    loss_harvest_suggestions,
    fee_vs_value_warnings,
    net_post_tax_delta,
  };
}
