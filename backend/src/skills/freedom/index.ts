/**
 * Freedom Score skill — TS port of the v5 model.
 * 5 pillars (weights 15/20/35/15/15), all clamped 0..100.
 * City-sensitive insurance multiplier (1.25 metro, 1.00 non-metro).
 */
import type { FreedomOutput, PlanState } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';

const WEIGHTS = { liquidity: 0.15, debt: 0.20, investment: 0.35, discipline: 0.15, risk: 0.15 };

export async function score(args: { household_id: string }): Promise<FreedomOutput | { error: string }> {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  return computeFreedom(plan);
}

export function computeFreedom(plan: PlanState): FreedomOutput {
  const fsi = plan.freedom_score_inputs ?? {};
  const monthlyIncome = fsi.monthly_income ?? 0;
  const monthlyExpenses = fsi.monthly_expenses ?? 0;
  const monthlyEmi = fsi.monthly_emi ?? 0;
  const liquid = fsi.liquid_assets_current_value ?? sum(plan.liquid_capital);
  const portfolio = fsi.portfolio_current_value ?? 0;
  const equityPct = fsi.equity_allocation_percent ?? 0;
  const dependents = plan.personal_details.dependents ?? 0;
  const annualIncome = monthlyIncome * 12;
  const cityMult = (plan.personal_details.city_type ?? 'Non-metro') === 'Metro' ? 1.25 : 1.0;

  // Liquidity pillar — emergency fund coverage & idle cash adequacy.
  const monthsCover = monthlyExpenses > 0 ? liquid / monthlyExpenses : 0;
  const liquidity = clamp(((monthsCover / 6) * 100), 0, 100);

  // Debt pillar — EMI to income + (proxy) debt-to-asset.
  const emiToIncome = monthlyIncome > 0 ? monthlyEmi / monthlyIncome : 0;
  const emiScore = Math.max(0, (1 - emiToIncome / 0.5) * 100);
  const totalAssets = (fsi.liquid_assets_current_value ?? 0) + portfolio;
  const debts = sumDebts(plan);
  const dtaScore = totalAssets > 0 ? Math.max(0, (1 - debts / totalAssets / 0.6) * 100) : 50;
  const debt = clamp(emiScore * 0.6 + dtaScore * 0.4, 0, 100);

  // Investment pillar — portfolio scale vs. income (rough), diversification proxy.
  const portfolioVsIncome = annualIncome > 0 ? Math.min(portfolio / (annualIncome * 5), 1) : 0;
  const equityFit = clamp(equityPct / 100 * 100, 0, 100);
  const investment = clamp(portfolioVsIncome * 60 + equityFit * 0.4, 0, 100);

  // Discipline pillar — savings rate, SIP consistency, timeline readiness.
  const savings = monthlyIncome - monthlyExpenses - monthlyEmi;
  const savingsRate = monthlyIncome > 0 ? savings / monthlyIncome : 0;
  const savingsScore = clamp((savingsRate / 0.30) * 100, 0, 100);
  const sipScore = 70; // proxy until SIP consistency wired
  const targetAge = plan.personal_details.retirement_age_target ?? 60;
  const estimatedAge = estimateFreedomAge(plan);
  const timelineScore = estimatedAge <= targetAge ? 100 : Math.max(0, 100 - (estimatedAge - targetAge) * 10);
  const discipline = clamp(savingsScore * 0.45 + sipScore * 0.25 + timelineScore * 0.30, 0, 100);

  // Risk pillar — life cover + medical cover adequacy, city-sensitive.
  const requiredLifeCover = annualIncome * 10 * dependentLifeMult(dependents) * cityMult;
  const requiredMedicalCover = 500_000 * dependentMedMult(dependents) * cityMult;
  const lifeCover = plan.insurance_details.term_plan?.cover_amount ?? 0;
  const medCover = plan.insurance_details.health_insurance?.cover_amount ?? 0;
  const lifeScore = requiredLifeCover > 0 ? Math.min((lifeCover / requiredLifeCover) * 100, 100) : 0;
  const medScore = requiredMedicalCover > 0 ? Math.min((medCover / requiredMedicalCover) * 100, 100) : 0;
  const risk = clamp(lifeScore * 0.6 + medScore * 0.4, 0, 100);

  const raw =
    liquidity * WEIGHTS.liquidity +
    debt * WEIGHTS.debt +
    investment * WEIGHTS.investment +
    discipline * WEIGHTS.discipline +
    risk * WEIGHTS.risk;

  const profileMult = 1.0;
  const final = clamp(raw * profileMult, 0, 100);

  return {
    raw_weighted_score: Number(raw.toFixed(2)),
    profile_strength_multiplier: profileMult,
    final_score: Number(final.toFixed(2)),
    pillars: {
      liquidity: Number(liquidity.toFixed(2)),
      debt: Number(debt.toFixed(2)),
      investment: Number(investment.toFixed(2)),
      discipline: Number(discipline.toFixed(2)),
      risk: Number(risk.toFixed(2)),
    },
    estimated_freedom_age: Number(estimatedAge.toFixed(1)),
    freedom_age_gap: Math.max(0, Number((estimatedAge - targetAge).toFixed(1))),
    city_cover_multiplier: cityMult,
    required_life_cover: Number(requiredLifeCover.toFixed(0)),
    required_medical_cover: Number(requiredMedicalCover.toFixed(0)),
  };
}

function clamp(n: number, lo: number, hi: number): number {
  if (Number.isNaN(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}
function sum(o: Record<string, number | null | undefined>): number {
  return Object.values(o).reduce<number>((a, v) => a + (typeof v === 'number' ? v : 0), 0);
}
function sumDebts(plan: PlanState): number {
  const l = plan.loans_liabilities;
  return [l.home_loan, l.car_loan, l.personal_loan, l.credit_card_dues].reduce(
    (a, b) => a + (b?.outstanding_amount ?? 0),
    0,
  );
}
function dependentLifeMult(d: number): number {
  if (d <= 0) return 0.5;
  if (d === 1) return 1.0;
  if (d === 2) return 1.2;
  return 1.5;
}
function dependentMedMult(d: number): number {
  return Math.min(4, Math.max(1, d + 1));
}
function estimateFreedomAge(plan: PlanState): number {
  const fsi = plan.freedom_score_inputs ?? {};
  const monthlyExpenses = fsi.monthly_expenses ?? 0;
  const monthlyIncome = fsi.monthly_income ?? 0;
  const portfolio = fsi.portfolio_current_value ?? 0;
  const age = fsi.age ?? 30;
  const expectedReturn = (fsi.equity_allocation_percent ?? 50) / 100 * 0.10 + 0.07;
  const annualNeed = monthlyExpenses * 12;
  if (annualNeed === 0) return age;
  const target = annualNeed * 25;
  const annualSavings = (monthlyIncome - monthlyExpenses) * 12;
  if (annualSavings <= 0) return age + 60;
  // FV = PV(1+r)^n + PMT * (((1+r)^n - 1) / r) → solve for n via bisection
  let lo = 0, hi = 80;
  for (let i = 0; i < 50; i++) {
    const mid = (lo + hi) / 2;
    const fv = portfolio * Math.pow(1 + expectedReturn, mid) + annualSavings * (Math.pow(1 + expectedReturn, mid) - 1) / expectedReturn;
    if (fv < target) lo = mid; else hi = mid;
  }
  return age + lo;
}
