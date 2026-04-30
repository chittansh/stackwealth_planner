import { describe, it, expect } from 'vitest';
import { computeRisk } from '../src/skills/risk/index.js';
import { emptyPlanState } from '../src/types/plan-state.js';

describe('risk profile', () => {
  it('produces all four scores in 0..100', () => {
    const plan = emptyPlanState('hh-risk');
    plan.freedom_score_inputs = {
      monthly_income: 400_000,
      monthly_expenses: 180_000,
      monthly_emi: 30_000,
      liquid_assets_current_value: 1_500_000,
      age: 32,
      equity_allocation_percent: 60,
    };
    const r = computeRisk(plan, {
      volatility_reaction: 'hold_steady',
      risk_return_tradeoff: 'C',
      max_tolerable_loss: '20',
    });
    for (const s of [r.capacity_score, r.need_score, r.willingness_score, r.recommended_score]) {
      expect(s).toBeGreaterThanOrEqual(0);
      expect(s).toBeLessThanOrEqual(100);
    }
  });

  it("caps willingness at the volatility cap when the user says 'sell everything'", () => {
    const plan = emptyPlanState('hh-cautious');
    plan.freedom_score_inputs = { monthly_income: 200_000, monthly_expenses: 100_000, age: 40 };
    const r = computeRisk(plan, {
      volatility_reaction: 'sell_everything',
      risk_return_tradeoff: 'D',
      max_tolerable_loss: '>30',
    });
    expect(r.willingness_score).toBeLessThanOrEqual(30);
  });
});
