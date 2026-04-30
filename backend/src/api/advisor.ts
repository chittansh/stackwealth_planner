import { Hono } from 'hono';
import { getPlan, listAllHouseholds } from '../db/client.js';
import { listNews, scoreItemForPlan } from '../skills/news/index.js';

export const advisorRoute = new Hono();

advisorRoute.get('/clients', async (c) => {
  const ids = await listAllHouseholds();
  const news = listNews();
  const rows = await Promise.all(
    ids.map(async (id) => {
      const p = await getPlan(id);
      if (!p) return null;
      const fs = p.computed.freedom_score?.final_score ?? null;
      const news_count = news.filter((n) => scoreItemForPlan(n, p).relevance >= 0.15).length;
      return {
        household_id: id,
        name: p.personal_details.full_name ?? id,
        freedom_score: fs,
        headline: p.computed.headline_amount_at_horizon || null,
        biggest_gap: biggestGap(p),
        last_activity: humanize(new Date(p.last_updated_at)),
        news_count,
      };
    }),
  );
  return c.json({ rows: rows.filter(Boolean) });
});

advisorRoute.get('/highlights', async (c) => {
  const ids = await listAllHouseholds();
  const news = listNews();
  const items: { kind: 'score_drop' | 'tax_window' | 'news_alert'; client?: string; household_id?: string; text: string }[] = [];
  for (const id of ids) {
    const p = await getPlan(id);
    if (!p) continue;
    const fs = p.computed.freedom_score?.final_score ?? 0;
    if (fs > 0 && fs < 50) {
      items.push({
        kind: 'score_drop',
        client: p.personal_details.full_name ?? id,
        household_id: id,
        text: `${p.personal_details.full_name ?? id} — Freedom Score ${fs.toFixed(0)}/100, lowest pillar ${biggestGap(p)}`,
      });
    }
    const hot = news.filter((n) => scoreItemForPlan(n, p).relevance >= 0.4);
    if (hot.length) {
      items.push({
        kind: 'news_alert',
        client: p.personal_details.full_name ?? id,
        household_id: id,
        text: `${hot.length} high-relevance news item${hot.length > 1 ? 's' : ''} affect ${p.personal_details.full_name ?? id}`,
      });
    }
  }
  // FY-end nudge: Jan-Mar bumps a tax highlight.
  const m = new Date().getMonth(); // 0..11
  if (m === 0 || m === 1 || m === 2) {
    items.unshift({ kind: 'tax_window', text: 'FY-end window — review LTCG headroom across all clients.' });
  }
  return c.json({ items });
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
