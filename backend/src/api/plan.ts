/**
 * /api/plan — read + direct mutation endpoints for the canvas.
 * UI-driven inline edits hit these and run through the same source-priority
 * pipeline as agent-driven edits.
 */
import { Hono } from 'hono';
import { getPlan, savePlan } from '../db/client.js';
import { applySet, applyAdd, applyRemove, applyAssumption } from '../skills/scenario/index.js';
import { emptyPlanState } from '../types/plan-state.js';

export const planRoute = new Hono();

planRoute.get('/:id', async (c) => {
  const id = c.req.param('id');
  let plan = await getPlan(id);
  if (!plan) {
    plan = emptyPlanState(id);
    await savePlan(plan);
  }
  return c.json(plan);
});

planRoute.post('/:id/set', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ path: string; value: unknown; source_type?: 'user' }>();
  const r = await applySet({ household_id: id, path: body.path, value: body.value, source_type: body.source_type ?? 'user' });
  return c.json(r);
});

planRoute.post('/:id/add', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ path: string; row: unknown }>();
  const r = await applyAdd({ household_id: id, path: body.path, row: body.row, source_type: 'user' });
  return c.json(r);
});

planRoute.post('/:id/remove', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ path: string; id: string }>();
  const r = await applyRemove({ household_id: id, path: body.path, id: body.id });
  return c.json(r);
});

planRoute.post('/:id/assumption', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ path: string; value: unknown }>();
  const r = await applyAssumption({ household_id: id, path: body.path, value: body.value });
  return c.json(r);
});
