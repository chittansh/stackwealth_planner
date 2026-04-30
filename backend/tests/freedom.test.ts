import { describe, it, expect } from 'vitest';
import { computeFreedom } from '../src/skills/freedom/index.js';
import { emptyPlanState } from '../src/types/plan-state.js';

describe('freedom score', () => {
  it('returns a score between 0 and 100 for an empty plan', () => {
    const plan = emptyPlanState('hh-empty');
    const r = computeFreedom(plan);
    expect(r.final_score).toBeGreaterThanOrEqual(0);
    expect(r.final_score).toBeLessThanOrEqual(100);
    expect(r.pillars.liquidity).toBeGreaterThanOrEqual(0);
  });

  it('rewards a household with strong liquidity + investment', () => {
    const plan = emptyPlanState('hh-strong');
    plan.personal_details.dependents = 1;
    plan.personal_details.city_type = 'Metro';
    plan.freedom_score_inputs = {
      portfolio_current_value: 30_000_000,
      liquid_assets_current_value: 5_000_000,
      monthly_income: 600_000,
      monthly_expenses: 200_000,
      monthly_emi: 50_000,
      age: 36,
      equity_allocation_percent: 65,
      number_of_holdings: 12,
    };
    plan.insurance_details.term_plan = { company: 'X', cover_amount: 50_000_000, annual_premium: 20_000 };
    plan.insurance_details.health_insurance = { company: 'Y', cover_amount: 1_500_000, annual_premium: 22_000 };
    const r = computeFreedom(plan);
    expect(r.final_score).toBeGreaterThan(50);
    expect(r.pillars.liquidity).toBeGreaterThan(50);
  });

  it('caps multipliers + score for cities and dependents', () => {
    const plan = emptyPlanState('hh-metro');
    plan.personal_details.dependents = 3;
    plan.personal_details.city_type = 'Metro';
    plan.freedom_score_inputs = { monthly_income: 200_000, monthly_expenses: 150_000, age: 40 };
    const r = computeFreedom(plan);
    expect(r.city_cover_multiplier).toBe(1.25);
    expect(r.required_life_cover).toBeGreaterThan(0);
  });
});
