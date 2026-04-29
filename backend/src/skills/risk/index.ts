/**
 * Risk profile skill — 3-part Capacity / Need / Willingness, reconciled.
 * Mirrors `risk-profile-assessor/references/scoring-logic.md`.
 */
import type { PlanState, RiskOutput, Goal } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';

const VOL_MAP = { sell_everything: 10, sell_some: 30, hold_steady: 60, buy_more: 90 } as const;
const RR_MAP = { A: 15, B: 40, C: 65, D: 90 } as const;
const LOSS_MAP = { '0': 10, '10': 30, '20': 55, '30': 75, '>30': 90 } as const;
const VOL_CAP = { sell_everything: 30, sell_some: 50, hold_steady: 100, buy_more: 100 } as const;

type Willingness = {
  volatility_reaction?: keyof typeof VOL_MAP;
  risk_return_tradeoff?: keyof typeof RR_MAP;
  max_tolerable_loss?: keyof typeof LOSS_MAP;
};

export async function assess(args: {
  household_id: string;
  willingness?: Willingness;
}): Promise<RiskOutput | { error: string }> {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  return computeRisk(plan, args.willingness ?? {});
}

export function computeRisk(plan: PlanState, w: Willingness): RiskOutput {
  // ── Willingness ────────────────────────────────────────────────────────
  const vol = w.volatility_reaction ? VOL_MAP[w.volatility_reaction] : 60;
  const rr = w.risk_return_tradeoff ? RR_MAP[w.risk_return_tradeoff] : 65;
  const loss = w.max_tolerable_loss ? LOSS_MAP[w.max_tolerable_loss] : 55;
  const willingnessRaw = vol * 0.30 + rr * 0.40 + loss * 0.30;
  const cap = w.volatility_reaction ? VOL_CAP[w.volatility_reaction] : 100;
  const willingnessScore = Math.min(willingnessRaw, cap);

  // ── Capacity ───────────────────────────────────────────────────────────
  const fsi = plan.freedom_score_inputs ?? {};
  const annualIncome = (fsi.monthly_income ?? 0) * 12;
  const monthlyExpenses = fsi.monthly_expenses ?? 0;
  const monthlyEmi = fsi.monthly_emi ?? 0;
  const liquid = fsi.liquid_assets_current_value ?? 0;
  const monthlyIncome = fsi.monthly_income ?? 0;
  const surplus = monthlyIncome - monthlyExpenses - monthlyEmi;
  const surplusRatio = monthlyIncome > 0 ? surplus / monthlyIncome : 0;
  const efMonths = monthlyExpenses > 0 ? liquid / monthlyExpenses : 0;
  const horizon = primaryHorizon(plan.financial_goals);

  const horizonCap = horizon <= 2 ? 30 : horizon <= 5 ? 55 : horizon <= 10 ? 75 : 100;
  const stabilityCap = 80; // proxy until income-stability data wired
  const efCap = efMonths < 1 ? 35 : efMonths < 3 ? 55 : efMonths < 6 ? 75 : 100;
  const surplusCap =
    surplusRatio < 0.10 ? 40 :
    surplusRatio < 0.20 ? 55 :
    surplusRatio < 0.35 ? 70 :
    surplusRatio < 0.50 ? 85 : 100;
  const expCap = 75; // proxy

  const caps = { horizon: horizonCap, stability: stabilityCap, ef: efCap, surplus: surplusCap, exp: expCap };
  const bindingEntry = Object.entries(caps).reduce((min, cur) => (cur[1] < min[1] ? cur : min), ['none', 100] as [string, number]);
  const capacityScore = bindingEntry[1];
  const capacityProfile = profileFromScore(capacityScore);

  // ── Need ───────────────────────────────────────────────────────────────
  const investableGoals = plan.financial_goals.filter((g) => g.kind !== 'foreign_travel');
  const goalNeeds = investableGoals.map((g) => goalNeed(g, plan.assumptions.inflation));
  const driver = goalNeeds.sort((a, b) => weightedNeed(b) - weightedNeed(a))[0];
  const needScore = driver?.need_score ?? 0;
  const needProfile = profileFromScore(needScore);

  // ── Reconciliation ────────────────────────────────────────────────────
  const prudentCeiling = Math.min(capacityScore, willingnessScore);
  const recommended = needScore <= prudentCeiling - 15 ? Math.max(needScore + 5, 20) : Math.min(needScore, prudentCeiling);
  const recommendedProfile = profileFromScore(recommended);
  const alignment: RiskOutput['alignment_status'] =
    needScore <= prudentCeiling && Math.abs(needScore - prudentCeiling) <= 15 ? 'aligned' :
    needScore < prudentCeiling - 15 ? 'need_below_ceiling' :
    needScore > prudentCeiling ? 'goal_risk_mismatch' :
    investableGoals.length === 0 ? 'need_unavailable' : 'incomplete';

  const warnings: string[] = [];
  if (alignment === 'goal_risk_mismatch') warnings.push('Goals require more risk than is prudent. Consider planning changes.');
  if (efMonths < 3) warnings.push('Emergency fund covers less than 3 months. Build reserves before adding risk.');

  const goalActions: string[] = [];
  if (alignment === 'goal_risk_mismatch') {
    goalActions.push('Increase periodic contribution', 'Extend horizon', 'Reduce target amount', 'Split goal into essential and aspirational');
  }

  return {
    capacity_score: Number(capacityScore.toFixed(0)),
    capacity_profile: capacityProfile,
    capacity_binding_cap: bindingEntry[0],
    need_score: Number(needScore.toFixed(0)),
    need_profile: needProfile,
    need_primary_goal: driver?.goal_name,
    need_driver_goals: goalNeeds.slice(0, 3).map((g) => g.goal_name),
    willingness_score: Number(willingnessScore.toFixed(0)),
    willingness_raw_score: Number(willingnessRaw.toFixed(2)),
    willingness_profile: profileFromScore(willingnessScore),
    prudent_ceiling: Number(prudentCeiling.toFixed(0)),
    recommended_score: Number(recommended.toFixed(0)),
    recommended_profile: recommendedProfile,
    alignment_status: alignment,
    key_warnings: warnings,
    goal_actions: goalActions,
  };
}

function profileFromScore(s: number): string {
  if (s <= 20) return 'Conservative';
  if (s <= 40) return 'Moderately Conservative';
  if (s <= 60) return 'Moderate';
  if (s <= 75) return 'Moderately Aggressive';
  return 'Aggressive';
}

function primaryHorizon(goals: Goal[]): number {
  if (!goals.length) return 10;
  return Math.min(...goals.map((g) => g.horizon_years ?? 10));
}

type GoalNeed = { goal_name: string; need_score: number; required_return: number; priority: number };

function goalNeed(g: Goal, inflation: number): GoalNeed {
  const pv = g.current_allocated_amount ?? 0;
  const pmt = (g.periodic_contribution ?? 0) * (g.contribution_frequency === 'monthly' ? 12 : 1);
  const n = g.horizon_years ?? 10;
  let target = g.target_amount ?? 0;
  if (g.is_target_in_today_money && (g.inflation_assumed ?? inflation)) {
    target = target * Math.pow(1 + (g.inflation_assumed ?? inflation), n);
  }
  const r = g.required_return_override ?? bisectRequiredReturn(pv, pmt, n, target);
  const need =
    r <= 0.04 ? 15 :
    r <= 0.06 ? 25 :
    r <= 0.08 ? 40 :
    r <= 0.10 ? 55 :
    r <= 0.12 ? 70 :
    r <= 0.14 ? 85 : 95;
  const priorityW = g.priority === 'essential' ? 1.0 : g.priority === 'important' ? 0.7 : 0.4;
  return { goal_name: g.goal_name, need_score: need, required_return: r, priority: priorityW };
}

function weightedNeed(g: GoalNeed): number {
  return g.need_score * g.priority;
}

function bisectRequiredReturn(pv: number, pmt: number, n: number, target: number): number {
  if (target <= 0 || n <= 0) return 0;
  let lo = 0, hi = 0.30;
  const f = (r: number) => {
    if (r === 0) return pv + pmt * n - target;
    return pv * Math.pow(1 + r, n) + pmt * (Math.pow(1 + r, n) - 1) / r - target;
  };
  if (f(lo) >= 0) return lo;
  if (f(hi) <= 0) return hi;
  for (let i = 0; i < 50; i++) {
    const mid = (lo + hi) / 2;
    if (f(mid) < 0) lo = mid; else hi = mid;
  }
  return Math.min(0.25, (lo + hi) / 2);
}
