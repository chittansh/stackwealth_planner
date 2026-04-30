import { Hono } from 'hono';
import { getPlan, listAllHouseholds } from '../db/client.js';

export const advisorRoute = new Hono();

advisorRoute.get('/clients', async (c) => {
  const ids = await listAllHouseholds();
  const rows = await Promise.all(
    ids.map(async (id) => {
      const p = await getPlan(id);
      if (!p) return null;
      const fs = p.computed.freedom_score?.final_score ?? null;
      return {
        household_id: id,
        name: p.personal_details.full_name ?? id,
        freedom_score: fs,
        headline: p.computed.headline_amount_at_horizon || null,
        biggest_gap: biggestGap(p),
        last_activity: humanize(new Date(p.last_updated_at)),
        news_count: 0,
      };
    }),
  );
  return c.json({ rows: rows.filter(Boolean) });
});

function biggestGap(p: import('../types/plan-state.js').PlanState): string {
  if (!p.computed.freedom_score) return 'risk profile not set';
  const pillars = p.computed.freedom_score.pillars;
  const lowest = Object.entries(pillars).sort((a, b) => a[1] - b[1])[0];
  if (!lowest) return '—';
  const map: Record<string, string> = {
    liquidity: 'liquidity weak',
    debt: 'debt heavy',
    investment: 'investment thin',
    discipline: 'savings rate low',
    risk: 'insurance gap',
  };
  return `${map[lowest[0]] ?? lowest[0]} (${lowest[1].toFixed(0)}/100)`;
}

function humanize(d: Date): string {
  const now = Date.now();
  const diff = now - d.getTime();
  const m = Math.round(diff / 60_000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr ago`;
  const days = Math.round(h / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}
