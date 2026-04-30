/**
 * News relevance scorer + in-memory news store.
 *
 * Scoring (per the design plan): sector exposure × direct holdings × MFs ×
 * asset class. We compute a 0..1 relevance per (news_item, household).
 */
import type { PlanState } from '../../types/plan-state.js';
import { getPlan } from '../../db/client.js';
import { listAllHouseholds } from '../../db/client.js';

export type NewsItem = {
  id: string;
  title: string;
  summary: string;
  sectors: string[];
  isins: string[];
  asset_class: 'equity' | 'debt' | 'gold' | 'cash' | 'macro';
  published_at: string;
};

const STORE: NewsItem[] = [];

export function seedNews(items: NewsItem[]) {
  STORE.length = 0;
  STORE.push(...items);
}

export function listNews(): NewsItem[] {
  return STORE.slice().sort((a, b) => (a.published_at < b.published_at ? 1 : -1));
}

export function scoreItemForPlan(item: NewsItem, plan: PlanState): { relevance: number; rationale: string } {
  let score = 0;
  const reasons: string[] = [];

  const isinSet = new Set([
    ...plan.mutual_funds.map((h) => h.isin).filter(Boolean) as string[],
    ...plan.equity_stocks.map((h) => h.isin).filter(Boolean) as string[],
  ]);
  const directHits = item.isins.filter((i) => isinSet.has(i));
  if (directHits.length) {
    score += Math.min(0.6, directHits.length * 0.25);
    reasons.push(`direct holding (${directHits.length})`);
  }

  // Sector heuristic: if any holding name contains a sector keyword
  const allNames = [
    ...plan.mutual_funds.map((h) => (h.fund_name ?? '').toLowerCase()),
    ...plan.equity_stocks.map((h) => (h.stock_name ?? '').toLowerCase()),
  ];
  const sectorHits = item.sectors.filter((s) => allNames.some((n) => n.includes(s.toLowerCase())));
  if (sectorHits.length) {
    score += Math.min(0.3, sectorHits.length * 0.1);
    reasons.push(`sector overlap (${sectorHits.join(', ')})`);
  }

  // Asset-class heuristic: equity dominance vs. allocation recommendation
  const eq = plan.computed.allocation?.recommended_allocation.equity ?? 50;
  if (item.asset_class === 'equity' && eq >= 50) {
    score += 0.2;
    reasons.push('high equity exposure');
  }
  if (item.asset_class === 'macro') {
    score += 0.1;
    reasons.push('macro');
  }

  return {
    relevance: Math.max(0, Math.min(1, Number(score.toFixed(2)))),
    rationale: reasons.join(' · ') || 'no direct exposure',
  };
}

export async function relevanceForHousehold(args: { household_id: string; top_k: number }) {
  const plan = await getPlan(args.household_id);
  if (!plan) return { items: [] };
  const scored = STORE.map((it) => ({
    news_id: it.id,
    title: it.title,
    ...scoreItemForPlan(it, plan),
  }))
    .sort((a, b) => b.relevance - a.relevance)
    .slice(0, args.top_k ?? 5);
  return { items: scored };
}

export async function affectedClientsForItem(item: NewsItem) {
  const ids = await listAllHouseholds();
  const out: { household_id: string; name: string; relevance: number; rationale: string }[] = [];
  for (const id of ids) {
    const plan = await getPlan(id);
    if (!plan) continue;
    const s = scoreItemForPlan(item, plan);
    if (s.relevance >= 0.15) {
      out.push({
        household_id: id,
        name: plan.personal_details.full_name ?? id,
        relevance: s.relevance,
        rationale: s.rationale,
      });
    }
  }
  return out.sort((a, b) => b.relevance - a.relevance);
}
