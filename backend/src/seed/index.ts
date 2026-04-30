/**
 * Demo seed — runs once on boot. Idempotent: skips if a household with the
 * same id already exists. Populates:
 *   - 3 households (one rich Hiro-style demo, two synthetic for advisor list)
 *   - News store (5 items)
 *   - Knowledge base (1 firm policy memo)
 */
import { randomUUID } from 'node:crypto';
import { emptyPlanState, type PlanState } from '../types/plan-state.js';
import { getPlan, savePlan, seedMemory } from '../db/client.js';
import { computeFreedom } from '../skills/freedom/index.js';
import { computeCashflow } from '../skills/cashflow/index.js';
import { seedNews } from '../skills/news/index.js';
import { ingestDocument } from '../skills/knowledge/index.js';

const RUN_ONCE_KEY = '__sw_seed_done__';
type GlobalShape = { [RUN_ONCE_KEY]?: boolean };

export async function runSeed() {
  const g = globalThis as GlobalShape;
  if (g[RUN_ONCE_KEY]) return;
  g[RUN_ONCE_KEY] = true;

  await ensureDemo();
  await ensureSecondary('hh-arora', 'The Aroras', 'Bengaluru', 'Metro');
  await ensureSecondary('hh-mehta', 'Mehta Family', 'Pune', 'Non-metro');

  seedNews([
    {
      id: 'n1',
      title: 'RBI holds repo at 6.50% — softer guidance',
      summary: 'MPC stays on hold; soft commentary on inflation trajectory hints at a cut window opening later this year.',
      sectors: ['Banks', 'NBFC', 'Real estate'],
      isins: [],
      asset_class: 'macro',
      published_at: new Date(Date.now() - 86_400_000 * 1).toISOString(),
    },
    {
      id: 'n2',
      title: 'Nifty IT slips on weak US discretionary print',
      summary: 'Mid-tier IT names fall as US client budgets remain cautious heading into FY27.',
      sectors: ['IT', 'Technology'],
      isins: ['INE009A01021', 'INE467B01029'],
      asset_class: 'equity',
      published_at: new Date(Date.now() - 86_400_000 * 2).toISOString(),
    },
    {
      id: 'n3',
      title: 'Auto sales hit 6-month high; rural recovery firms up',
      summary: 'Tractor + 2W volumes lead, premium SUVs continue. Buys for cyclicals.',
      sectors: ['Auto', 'Capital Goods'],
      isins: ['INE585B01010'],
      asset_class: 'equity',
      published_at: new Date(Date.now() - 86_400_000 * 3).toISOString(),
    },
    {
      id: 'n4',
      title: 'Crude rallies on geopolitical headlines',
      summary: 'Brent over $90 — watch INR and OMC margins.',
      sectors: ['Energy'],
      isins: [],
      asset_class: 'macro',
      published_at: new Date(Date.now() - 86_400_000 * 4).toISOString(),
    },
    {
      id: 'n5',
      title: 'AMFI: equity MF inflows at record',
      summary: 'Domestic flows hit all-time high; SIP book steady.',
      sectors: [],
      isins: [],
      asset_class: 'equity',
      published_at: new Date(Date.now() - 86_400_000 * 5).toISOString(),
    },
  ]);

  await ingestDocument({
    org_id: 'demo',
    filename: 'firm-mf-policy-v3.md',
    text: `# Firm MF Policy v3

## Diversification limits
- Single AMC exposure cap: 40% of total MF allocation.
- Top 3 holdings cap: 65%.

## SIP discipline
- All client SIPs must be set up via mandate; ad-hoc lump sums require advisor sign-off.

## Allocation guardrails
- Equity overweight in expensive markets is capped per the tactical framework.
- Liquidity floor: 6 months of household expenses in cash + liquid funds.

## Tax
- Gain harvesting up to ₹1.25 L LTCG headroom is encouraged annually if fee/value > 2x.
`,
  }).catch(() => undefined);

  console.log('[seed] demo households + news + KB ready');
}

async function ensureDemo() {
  const existing = await getPlan('demo');
  if (existing && existing.computed.headline_amount_at_horizon > 0) return;

  const plan: PlanState = emptyPlanState('demo');
  plan.personal_details = {
    full_name: 'Jim & Pam',
    date_of_birth: '15-04-1990',
    pan: 'ABCDE1234F',
    email: 'jim@example.com',
    mobile: '9999999999',
    marital_status: 'Married',
    spouse_name_and_age: 'Pam, 34',
    number_of_children: 1,
    dependents: 2,
    city_of_residence: 'Mumbai',
    city_type: 'Metro',
    occupation: 'Product manager',
    retirement_age_target: 60,
  };
  plan.income_details = {
    client_salary_in_hand: 250_000,
    spouse_salary_in_hand: 180_000,
    client_business_income: 0,
    spouse_business_income: 0,
    client_rental_income: 30_000,
    client_other_income: 0,
  };
  plan.monthly_expenses = {
    household_expenses: 25_000,
    rent_or_emi: 90_000,
    groceries: 30_000,
    utilities: 8_000,
    school_fees: 18_000,
    insurance_premium: 6_000,
    medical: 4_000,
    travel_or_lifestyle: 25_000,
    sip_investments: 80_000,
    other_emis: 10_000,
  };
  plan.monthly_investments = {
    mutual_fund_sip: 80_000,
    nps: 4_000,
    ppf: 12_500,
    rd: 0,
    direct_equity: 0,
    insurance_premium: 6_000,
    other: 0,
  };
  plan.liquid_capital = {
    savings_account_balance: 1_200_000,
    idle_cash_for_investment: 300_000,
    fd_breakable_for_investment: 500_000,
    bonus_expected_for_investment: 0,
  };
  plan.emergency_fund = {
    emergency_fund_available: true,
    total_emergency_corpus: 1_500_000,
    where_is_it_parked: 'Liquid mutual fund + savings',
    monthly_household_expense_for_calculation: 220_000,
    months_of_cover_available: 6.8,
  };
  plan.loans_liabilities.home_loan = { outstanding_amount: 14_000_000, emi: 90_000, interest_rate: 8.6, tenure_left: 18 };
  plan.insurance_details.term_plan = { company: 'HDFC Life', cover_amount: 25_000_000, annual_premium: 18_000 };
  plan.insurance_details.health_insurance = { company: 'Star Health', cover_amount: 1_500_000, annual_premium: 22_000 };
  plan.financial_goals = [
    {
      id: randomUUID(),
      goal_name: 'Retirement corpus',
      kind: 'retirement',
      target_year: 2050,
      target_amount: 80_000_000,
      current_allocated_amount: 6_000_000,
      periodic_contribution: 1_000_000,
      contribution_frequency: 'annual',
      horizon_years: 24,
      priority: 'essential',
      is_target_in_today_money: false,
      inflation_assumed: 0.06,
    },
    {
      id: randomUUID(),
      goal_name: 'Child education',
      kind: 'child_education',
      target_year: 2042,
      target_amount: 5_000_000,
      current_allocated_amount: 600_000,
      periodic_contribution: 240_000,
      contribution_frequency: 'annual',
      horizon_years: 16,
      priority: 'important',
      is_target_in_today_money: true,
      inflation_assumed: 0.08,
    },
    {
      id: randomUUID(),
      goal_name: 'Buy parent\'s house',
      kind: 'house_purchase',
      target_year: 2031,
      target_amount: 9_500_000,
      current_allocated_amount: 1_000_000,
      periodic_contribution: 500_000,
      contribution_frequency: 'annual',
      horizon_years: 5,
      priority: 'aspirational',
      is_target_in_today_money: false,
      inflation_assumed: 0.06,
    },
  ];
  plan.assumptions.persons = [
    { id: randomUUID(), name: 'Jim', date_of_birth: '15-04-1990', life_expectancy: 85, retirement_age: 60 },
    { id: randomUUID(), name: 'Pam', date_of_birth: '20-09-1992', life_expectancy: 87, retirement_age: 58 },
  ];
  plan.freedom_score_inputs = {
    portfolio_current_value: 9_000_000,
    liquid_assets_current_value: 2_000_000,
    monthly_income: 460_000,
    monthly_expenses: 220_000,
    monthly_emi: 90_000,
    age: 36,
    risk_tolerance: 'Moderate',
    equity_allocation_percent: 60,
    number_of_holdings: 12,
  };

  const cf = computeCashflow(plan, plan.computed.horizon_years || 45);
  plan.computed.freedom_score = computeFreedom(plan);
  plan.computed.cashflow = cf;
  plan.computed.cash_flow_table = cf.rows;
  plan.computed.net_worth_series = cf.retirement_glide.map((r) => ({ year: r.year, value: r.balance }));
  plan.computed.headline_amount_at_horizon = cf.rows[cf.rows.length - 1]?.total_net_worth ?? 0;
  plan.computed.net_worth = {
    assets_total:
      (plan.freedom_score_inputs.portfolio_current_value ?? 0) +
      (plan.freedom_score_inputs.liquid_assets_current_value ?? 0),
    liquid: plan.freedom_score_inputs.liquid_assets_current_value ?? 0,
    non_liquid: 0,
    debts_total: plan.loans_liabilities.home_loan?.outstanding_amount ?? 0,
    total:
      ((plan.freedom_score_inputs.portfolio_current_value ?? 0) +
        (plan.freedom_score_inputs.liquid_assets_current_value ?? 0)) -
      (plan.loans_liabilities.home_loan?.outstanding_amount ?? 0),
  };
  plan.computed.milestone_pins = plan.financial_goals
    .filter((g) => g.target_year)
    .map((g) => ({
      year: g.target_year!,
      label: g.goal_name,
      type: g.kind === 'house_purchase' ? 'home_purchase' : g.kind === 'child_education' ? 'education' : g.kind === 'retirement' ? 'retirement' : 'other',
      goal_id: g.id,
    }));
  plan.last_updated_at = new Date().toISOString();

  await savePlan(plan);
  seedMemory(plan);
}

async function ensureSecondary(id: string, name: string, city: string, type: 'Metro' | 'Non-metro') {
  const existing = await getPlan(id);
  if (existing && existing.personal_details.full_name) return;
  const plan: PlanState = emptyPlanState(id);
  plan.personal_details.full_name = name;
  plan.personal_details.city_of_residence = city;
  plan.personal_details.city_type = type;
  plan.personal_details.dependents = 2;
  plan.personal_details.retirement_age_target = 60;
  plan.income_details.client_salary_in_hand = 180_000;
  plan.monthly_expenses.rent_or_emi = 60_000;
  plan.monthly_expenses.groceries = 22_000;
  plan.liquid_capital.savings_account_balance = 600_000;
  plan.freedom_score_inputs = {
    portfolio_current_value: 3_500_000,
    liquid_assets_current_value: 700_000,
    monthly_income: 180_000,
    monthly_expenses: 110_000,
    monthly_emi: 30_000,
    age: 38,
    equity_allocation_percent: 55,
    number_of_holdings: 6,
  };
  const cf = computeCashflow(plan, plan.computed.horizon_years || 45);
  plan.computed.freedom_score = computeFreedom(plan);
  plan.computed.cashflow = cf;
  plan.computed.cash_flow_table = cf.rows;
  plan.computed.net_worth_series = cf.retirement_glide.map((r) => ({ year: r.year, value: r.balance }));
  plan.computed.headline_amount_at_horizon = cf.rows[cf.rows.length - 1]?.total_net_worth ?? 0;
  plan.computed.net_worth = {
    assets_total:
      (plan.freedom_score_inputs.portfolio_current_value ?? 0) +
      (plan.freedom_score_inputs.liquid_assets_current_value ?? 0),
    liquid: plan.freedom_score_inputs.liquid_assets_current_value ?? 0,
    non_liquid: 0,
    debts_total: 0,
    total:
      (plan.freedom_score_inputs.portfolio_current_value ?? 0) +
      (plan.freedom_score_inputs.liquid_assets_current_value ?? 0),
  };
  plan.last_updated_at = new Date().toISOString();
  await savePlan(plan);
  seedMemory(plan);
}
