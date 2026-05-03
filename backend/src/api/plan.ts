/**
 * /api/plan — read + direct mutation endpoints for the canvas.
 * UI-driven inline edits hit these and run through the same source-priority
 * pipeline as agent-driven edits.
 */
import { Hono } from 'hono';
import { randomUUID } from 'node:crypto';
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

/**
 * Create a new household with a friendly name. Returns the new id so the
 * client can navigate to /plan/:id. Idempotent if the same name + id is
 * passed.
 */
type CreateBody = { name?: string; advisor_id?: string; id?: string };
planRoute.post('/', async (c) => {
  const body: CreateBody = await c.req.json<CreateBody>().catch(() => ({}) as CreateBody);
  const id = body.id ?? `h_${randomUUID().slice(0, 8)}`;
  const existing = await getPlan(id);
  if (existing) {
    if (body.name) existing.personal_details.full_name = body.name;
    if (body.advisor_id) (existing as unknown as { advisor_id?: string }).advisor_id = body.advisor_id;
    await savePlan(existing);
    return c.json({ ok: true, id, created: false });
  }
  const plan = emptyPlanState(id);
  if (body.name) plan.personal_details.full_name = body.name;
  if (body.advisor_id) (plan as unknown as { advisor_id?: string }).advisor_id = body.advisor_id;
  await savePlan(plan);
  return c.json({ ok: true, id, created: true });
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
