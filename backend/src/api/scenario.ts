import { Hono } from 'hono';
import { pin, diff } from '../skills/scenario/index.js';
import { getPlan, savePlan } from '../db/client.js';

export const scenarioRoute = new Hono();

scenarioRoute.post('/:id/pin', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ label: string; mutation?: { ops: { path: string; op: 'set' | 'add' | 'remove'; value?: unknown; row?: unknown; id?: string }[] } }>();
  const result = await pin({ household_id: id, label: body.label, mutation: body.mutation });
  return c.json(result);
});

scenarioRoute.post('/:id/diff', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ a: string; b: string }>();
  const result = await diff({ household_id: id, a: body.a, b: body.b });
  return c.json(result);
});

scenarioRoute.post('/:id/toggle', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ id: string; active: boolean }>();
  const plan = await getPlan(id);
  if (!plan) return c.json({ ok: false }, 404);
  const set = new Set(plan.active_scenario_ids);
  if (body.active) set.add(body.id);
  else set.delete(body.id);
  plan.active_scenario_ids = [...set].slice(-3);
  await savePlan(plan);
  return c.json({ ok: true });
});

scenarioRoute.post('/:id/clear', async (c) => {
  const id = c.req.param('id');
  const plan = await getPlan(id);
  if (!plan) return c.json({ ok: false }, 404);
  plan.scenarios = [];
  plan.active_scenario_ids = [];
  await savePlan(plan);
  return c.json({ ok: true });
});
