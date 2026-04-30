import { describe, it, expect } from 'vitest';
import { computeCashflow } from '../src/skills/cashflow/index.js';
import { emptyPlanState } from '../src/types/plan-state.js';

describe('cash flow projection', () => {
  it('produces a row per horizon year', () => {
    const plan = emptyPlanState('hh-cf');
    plan.freedom_score_inputs = {
      monthly_income: 400_000,
      monthly_expenses: 180_000,
      monthly_emi: 60_000,
      portfolio_current_value: 8_000_000,
      liquid_assets_current_value: 2_000_000,
      age: 32,
      equity_allocation_percent: 60,
    };
    plan.personal_details.retirement_age_target = 60;
    const cf = computeCashflow(plan, 30);
    expect(cf.rows).toHaveLength(30);
    expect(cf.rows[0].assets).toBeGreaterThan(0);
    expect(cf.rows[29].total_net_worth).toBeGreaterThan(cf.rows[0].total_net_worth);
    expect(cf.monthly_strip_next_12mo).toHaveLength(12);
  });

  it('clamps income to zero past retirement age', () => {
    const plan = emptyPlanState('hh-retired');
    plan.freedom_score_inputs = { monthly_income: 100_000, monthly_expenses: 80_000, age: 65 };
    plan.personal_details.retirement_age_target = 60;
    const cf = computeCashflow(plan, 5);
    expect(cf.rows.every((r) => r.income === 0)).toBe(true);
  });
});
