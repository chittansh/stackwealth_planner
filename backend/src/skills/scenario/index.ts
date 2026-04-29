/**
 * Scenario engine + plan mutation core.
 *
 * Exports:
 *   applySet / applyAdd / applyRemove / applyAssumption  — direct plan edits
 *   pin / diff                                            — Plan A/B compare
 *   runMonteCarlo                                         — 2,000-path sim
 *
 * Day 4 hardens this. For now, uses an in-memory `getPlan` in db/client.ts.
 */
import { randomUUID } from 'node:crypto';
import type { PlanState, MCResult, Scenario, ScenarioMutation, ComputedSnapshot, EvidenceRow } from '../../types/plan-state.js';
import { sourceRank } from '../../types/plan-state.js';
import { getPlan, savePlan } from '../../db/client.js';
import { computeFreedom } from '../freedom/index.js';
import { computeCashflow } from '../cashflow/index.js';

export async function applySet(args: { household_id: string; path: string; value: unknown; source_type: EvidenceRow['source_type'] }) {
  const plan = await getPlan(args.household_id);
  if (!plan) return { ok: false, updated_path: args.path };
  enforceSourcePriority(plan, args.path, args.source_type, () => setPath(plan, args.path, args.value));
  await savePlan(recompute(plan));
  return { ok: true, updated_path: args.path };
}

export async function applyAdd(args: { household_id: string; path: string; row: unknown; source_type: EvidenceRow['source_type'] }) {
  const plan = await getPlan(args.household_id);
  if (!plan) return { ok: false, id: '' };
  const id = (args.row as { id?: string })?.id ?? randomUUID();
  const rowWithId = { ...(args.row as object), id };
  const list = (getPath(plan, args.path) as unknown[]) ?? [];
  setPath(plan, args.path, [...list, rowWithId]);
  await savePlan(recompute(plan));
  return { ok: true, id };
}

export async function applyRemove(args: { household_id: string; path: string; id: string }) {
  const plan = await getPlan(args.household_id);
  if (!plan) return { ok: false };
  const list = (getPath(plan, args.path) as { id: string }[]) ?? [];
  setPath(plan, args.path, list.filter((r) => r.id !== args.id));
  await savePlan(recompute(plan));
  return { ok: true };
}

export async function applyAssumption(args: { household_id: string; path: string; value: unknown }) {
  const plan = await getPlan(args.household_id);
  if (!plan) return { ok: false, updated_path: args.path };
  setPath(plan, args.path, args.value);
  await savePlan(recompute(plan));
  return { ok: true, updated_path: args.path };
}

export async function pin(args: { household_id: string; label: string; mutation?: ScenarioMutation }) {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  const cloned: PlanState = JSON.parse(JSON.stringify(plan));
  if (args.mutation) {
    for (const op of args.mutation.ops) {
      if (op.op === 'set') setPath(cloned, op.path, op.value);
      else if (op.op === 'add' && op.row) {
        const list = (getPath(cloned, op.path) as unknown[]) ?? [];
        setPath(cloned, op.path, [...list, op.row]);
      } else if (op.op === 'remove' && op.id) {
        const list = (getPath(cloned, op.path) as { id: string }[]) ?? [];
        setPath(cloned, op.path, list.filter((r) => r.id !== op.id));
      }
    }
  }
  const computed = recompute(cloned).computed;
  const scenario: Scenario = {
    id: randomUUID(),
    label: args.label,
    mutation: args.mutation ?? { ops: [] },
    computed,
  };
  plan.scenarios.push(scenario);
  plan.active_scenario_ids = [...plan.active_scenario_ids, scenario.id].slice(-3);
  await savePlan(plan);
  return scenario;
}

export async function diff(args: { household_id: string; a: string; b: string }) {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  const a = plan.scenarios.find((s) => s.id === args.a)?.computed;
  const b = plan.scenarios.find((s) => s.id === args.b)?.computed;
  if (!a || !b) return { error: 'scenario_not_found' };
  return {
    headline_delta: b.headline_amount_at_horizon - a.headline_amount_at_horizon,
    horizon_years: b.horizon_years,
  };
}

export async function runMonteCarlo(args: { household_id: string; paths: number }): Promise<MCResult | { error: string }> {
  const plan = await getPlan(args.household_id);
  if (!plan) return { error: 'household_not_found' };
  if (!plan.computed.risk_profile?.recommended_score) return { error: 'risk_gate_required' };
  const paths = Math.max(500, Math.min(10_000, args.paths ?? 2000));
  const fsi = plan.freedom_score_inputs ?? {};
  const equityPct = (fsi.equity_allocation_percent ?? 50) / 100;
  const mu = equityPct * 0.10 + (1 - equityPct) * 0.07;
  const sigma = equityPct * 0.18;
  const horizon = plan.computed.horizon_years || 45;
  const startAge = fsi.age ?? 30;
  const annualSavings = ((fsi.monthly_income ?? 0) - (fsi.monthly_expenses ?? 0) - (fsi.monthly_emi ?? 0)) * 12;
  const annualNeed = (fsi.monthly_expenses ?? 0) * 12;
  const target = annualNeed * 25;

  const ages: number[] = [];
  for (let p = 0; p < paths; p++) {
    let bal = (fsi.portfolio_current_value ?? 0) + (fsi.liquid_assets_current_value ?? 0);
    let yr = 0;
    while (yr < horizon && bal < target) {
      const ret = mu + sigma * randNormal();
      bal = bal * (1 + ret) + Math.max(annualSavings, 0);
      yr += 1;
    }
    ages.push(startAge + yr);
  }
  ages.sort((a, b) => a - b);
  const pct = (p: number) => ages[Math.floor((p / 100) * (ages.length - 1))];

  return {
    paths_count: paths,
    p10_freedom_age: pct(10),
    p50_freedom_age: pct(50),
    p90_freedom_age: pct(90),
    goal_success_probabilities: [],
  };
}

// ── helpers ─────────────────────────────────────────────────────────────

function recompute(plan: PlanState): PlanState {
  plan.computed.freedom_score = computeFreedom(plan);
  const cf = computeCashflow(plan, plan.computed.horizon_years || 45);
  plan.computed.cashflow = cf;
  plan.computed.cash_flow_table = cf.rows;
  plan.computed.net_worth_series = cf.retirement_glide.map((r) => ({ year: r.year, value: r.balance }));
  plan.computed.headline_amount_at_horizon = cf.rows[cf.rows.length - 1]?.total_net_worth ?? 0;
  plan.computed.milestone_pins = plan.financial_goals
    .filter((g) => g.target_year)
    .map((g) => ({
      year: g.target_year!,
      label: g.goal_name,
      type: g.kind === 'house_purchase' ? 'home_purchase' : g.kind === 'child_education' ? 'education' : g.kind === 'retirement' ? 'retirement' : g.kind === 'foreign_travel' ? 'travel' : 'other',
      goal_id: g.id,
    }));
  plan.last_updated_at = new Date().toISOString();
  return plan;
}

function getPath(o: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, k) => {
    if (acc == null) return undefined;
    if (Array.isArray(acc) && /^\d+$/.test(k)) return acc[Number(k)];
    return (acc as Record<string, unknown>)[k];
  }, o);
}

function setPath(o: unknown, path: string, value: unknown): void {
  const parts = path.split('.');
  let cur: unknown = o;
  for (let i = 0; i < parts.length - 1; i++) {
    const k = parts[i];
    const nextK = parts[i + 1];
    if (Array.isArray(cur) && /^\d+$/.test(k)) {
      cur = (cur as unknown[])[Number(k)];
    } else {
      const obj = cur as Record<string, unknown>;
      if (obj[k] == null) obj[k] = /^\d+$/.test(nextK) ? [] : {};
      cur = obj[k];
    }
  }
  const last = parts[parts.length - 1];
  if (Array.isArray(cur) && /^\d+$/.test(last)) (cur as unknown[])[Number(last)] = value;
  else (cur as Record<string, unknown>)[last] = value;
}

function enforceSourcePriority(plan: PlanState, path: string, incoming: EvidenceRow['source_type'], apply: () => void) {
  const existing = plan.evidence.filter((e) => e.field === path);
  const existingBest = existing.reduce<EvidenceRow | null>((best, e) => (best && sourceRank(best.source_type) <= sourceRank(e.source_type) ? best : e), null);
  if (existingBest && sourceRank(incoming) > sourceRank(existingBest.source_type)) return;
  apply();
  plan.evidence.push({
    field: path,
    value: getPath(plan, path),
    source_file: null,
    source_type: incoming,
    parser_tier: 'manual',
    confidence: 1.0,
    timestamp: new Date().toISOString(),
  });
}

function randNormal(): number {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
}
