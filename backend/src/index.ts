import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';

import { chatRoute } from './api/chat.js';
import { planRoute } from './api/plan.js';
import { uploadRoute } from './api/upload.js';
import { scenarioRoute } from './api/scenario.js';
import { skillRoute } from './api/skill.js';
import { advisorRoute } from './api/advisor.js';
import { householdRoute } from './api/household.js';
import { knowledgeRoute } from './api/knowledge.js';
import { newsRoute } from './api/news.js';
import { reportRoute } from './api/report.js';

import { runSeed } from './seed/index.js';

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
app.route('/api/scenario', scenarioRoute);
app.route('/api/skill', skillRoute);
app.route('/api/advisor', advisorRoute);
app.route('/api/household', householdRoute);
app.route('/api/knowledge', knowledgeRoute);
app.route('/api/news', newsRoute);
app.route('/api/report', reportRoute);

// Seed demo data on boot (idempotent).
runSeed().catch((err) => console.error('[seed] failed:', err));

const port = Number(process.env.PORT ?? 4000);
serve({ fetch: app.fetch, port }, (info) => {
  console.log(`[stackwealth] listening on :${info.port}`);
});
