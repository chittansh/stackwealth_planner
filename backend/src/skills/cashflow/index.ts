/**
 * Cash-flow projection — year-by-year + 12-month strip + retirement glide.
 * The output `rows` feeds the Cash Flow grid view.
 */
import type { CashFlowProjection, CashFlowRow, PlanState } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';

export async function project(args: {
  household_id: string;
  horizon_years: number;
}): Promise<CashFlowProjection | { error: string }> {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  return computeCashflow(plan, args.horizon_years ?? 45);
}

export function computeCashflow(plan: PlanState, horizon: number): CashFlowProjection {
  const fsi = plan.freedom_score_inputs ?? {};
  const startYear = new Date().getFullYear();
  const startAge = fsi.age ?? 30;
  const monthlyIncome = fsi.monthly_income ?? 0;
  const monthlyExpenses = fsi.monthly_expenses ?? 0;
  const monthlyEmi = fsi.monthly_emi ?? 0;
  const equityPct = (fsi.equity_allocation_percent ?? 50) / 100;
  const expectedReturn = equityPct * 0.10 + (1 - equityPct) * 0.07;
  const inflation = plan.assumptions.inflation;
  const taxes = plan.assumptions.taxes.federal + plan.assumptions.taxes.state + plan.assumptions.taxes.capital_gains;

  const retirementAge = plan.personal_details.retirement_age_target ?? 60;
  let assets = (fsi.portfolio_current_value ?? 0) + (fsi.liquid_assets_current_value ?? 0);
  const rows: CashFlowRow[] = [];

  for (let i = 0; i < horizon; i++) {
    const year = startYear + i;
    const age = startAge + i;
    const earning = age < retirementAge;
    const annualIncome = earning ? monthlyIncome * 12 * Math.pow(1 + inflation * 0.5, i) : 0;
    const annualExpenses = monthlyExpenses * 12 * Math.pow(1 + inflation, i);
    const annualEmi = earning ? monthlyEmi * 12 : 0;
    const annualTax = annualIncome * (taxes * 0.4); // simplified effective tax
    const retirementContrib = earning ? Math.max(0, annualIncome * 0.20 - annualTax * 0) : 0;
    const net = annualIncome - annualExpenses - annualEmi - annualTax;
    assets = assets * (1 + expectedReturn) + Math.max(net, 0);

    rows.push({
      year,
      age,
      assets: Math.round(assets),
      income: Math.round(annualIncome),
      expenses: Math.round(annualExpenses),
      taxes: Math.round(annualTax),
      retirement_contributions: Math.round(retirementContrib),
      other: 0,
      total_net_worth: Math.round(assets),
    });
  }

  const monthly_strip_next_12mo = Array.from({ length: 12 }, (_, m) => ({
    month: new Date(startYear, m, 1).toLocaleString('default', { month: 'short' }),
    inflow: monthlyIncome,
    outflow: monthlyExpenses + monthlyEmi,
  }));

  const retirement_glide = rows.map((r) => ({ year: r.year, balance: r.total_net_worth }));

  return { rows, monthly_strip_next_12mo, retirement_glide };
}
