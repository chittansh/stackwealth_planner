import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';

import { chatRoute } from './api/chat.js';
import { planRoute } from './api/plan.js';
import { uploadRoute } from './api/upload.js';

const app = new Hono();

app.use('*', logger());
app.use(
  '*',
  cors({
    origin: process.env.FRONTEND_ORIGIN ?? 'http://localhost:3000',
    credentials: true,
  }),
);

app.get('/', (c) => c.json({ name: 'stackwealth-planner-backend', status: 'ok' }));
app.get('/health', (c) => c.json({ ok: true, ts: new Date().toISOString() }));

app.route('/api/chat', chatRoute);
app.route('/api/plan', planRoute);
app.route('/api/upload', uploadRoute);

const port = Number(process.env.PORT ?? 4000);
serve({ fetch: app.fetch, port }, (info) => {
  console.log(`[stackwealth] listening on :${info.port}`);
});
