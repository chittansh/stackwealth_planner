/**
 * Direct REST entry points for skills, used by canvas widgets that don't
 * need to go through the agent (eg. "Run tax review" button, manual MC).
 */
import { Hono } from 'hono';
import { score as freedomScore } from '../skills/freedom/index.js';
import { recommend as allocate } from '../skills/allocate/index.js';
import { harvest as taxHarvest } from '../skills/tax/index.js';
import { project as cashflow } from '../skills/cashflow/index.js';
import { runMonteCarlo } from '../skills/scenario/index.js';
import { assess as risk } from '../skills/risk/index.js';
import { getPlan, savePlan } from '../db/client.js';
import { computeAllocation } from '../skills/allocate/index.js';

export const skillRoute = new Hono();

skillRoute.post('/risk/:id', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ willingness?: { volatility_reaction?: 'sell_everything' | 'sell_some' | 'hold_steady' | 'buy_more'; risk_return_tradeoff?: 'A' | 'B' | 'C' | 'D'; max_tolerable_loss?: '0' | '10' | '20' | '30' | '>30' } }>().catch(() => ({}));
  const r = await risk({ household_id: id, willingness: body?.willingness });
  // Persist on the plan's computed slot.
  const plan = await getPlan(id);
  if (plan && r && !('error' in r)) {
    plan.computed.risk_profile = r;
    // Allocation can now run.
    plan.computed.allocation = computeAllocation(plan);
    plan.last_updated_at = new Date().toISOString();
    await savePlan(plan);
  }
  return c.json(r);
});

skillRoute.post('/freedom/:id', async (c) => {
  const id = c.req.param('id');
  const r = await freedomScore({ household_id: id });
  const plan = await getPlan(id);
  if (plan && r && !('error' in r)) {
    plan.computed.freedom_score = r;
    plan.last_updated_at = new Date().toISOString();
    await savePlan(plan);
  }
  return c.json(r);
});

skillRoute.post('/allocate/:id', async (c) => {
  const id = c.req.param('id');
  const r = await allocate({ household_id: id });
  const plan = await getPlan(id);
  if (plan && r && !('error' in r)) {
    plan.computed.allocation = r;
    plan.last_updated_at = new Date().toISOString();
    await savePlan(plan);
  }
  return c.json(r);
});

skillRoute.post('/tax/:id', async (c) => {
  const id = c.req.param('id');
  const r = await taxHarvest({ household_id: id });
  const plan = await getPlan(id);
  if (plan && r && !('error' in r)) {
    plan.computed.tax = r;
    plan.last_updated_at = new Date().toISOString();
    await savePlan(plan);
  }
  return c.json(r);
});

skillRoute.post('/cashflow/:id', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ horizon_years?: number }>().catch(() => ({}));
  const r = await cashflow({ household_id: id, horizon_years: body?.horizon_years ?? 45 });
  const plan = await getPlan(id);
  if (plan && r && !('error' in r)) {
    plan.computed.cashflow = r;
    plan.computed.cash_flow_table = r.rows;
    plan.last_updated_at = new Date().toISOString();
    await savePlan(plan);
  }
  return c.json(r);
});

skillRoute.post('/montecarlo/:id', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ paths?: number }>().catch(() => ({}));
  const r = await runMonteCarlo({ household_id: id, paths: body?.paths ?? 2000 });
  const plan = await getPlan(id);
  if (plan && r && !('error' in r)) {
    plan.computed.monte_carlo = r;
    plan.last_updated_at = new Date().toISOString();
    await savePlan(plan);
  }
  return c.json(r);
});
