import { Hono } from 'hono';
import { merge, preview } from '../skills/household/merge.js';

export const householdRoute = new Hono();

householdRoute.post('/preview', async (c) => {
  const body = await c.req.json<{ household_ids: string[] }>();
  return c.json(await preview(body));
});

householdRoute.post('/merge', async (c) => {
  const body = await c.req.json<{ household_ids: string[] }>();
  return c.json(await merge(body));
});
