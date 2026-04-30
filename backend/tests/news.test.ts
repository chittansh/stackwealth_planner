import { describe, it, expect } from 'vitest';
import { seedNews, scoreItemForPlan } from '../src/skills/news/index.js';
import { emptyPlanState } from '../src/types/plan-state.js';

describe('news relevance scorer', () => {
  it('scores 0 for a debt-only news item against an empty plan', () => {
    seedNews([]);
    const plan = emptyPlanState('hh-zero');
    const r = scoreItemForPlan(
      {
        id: 'n-zero',
        title: 'G-Sec yields drift',
        summary: '...',
        sectors: ['Banks'],
        isins: [],
        asset_class: 'debt',
        published_at: new Date().toISOString(),
      },
      plan,
    );
    expect(r.relevance).toBe(0);
  });

  it('boosts items with a direct ISIN hit', () => {
    const plan = emptyPlanState('hh-isin');
    plan.equity_stocks = [
      {
        id: 'eq1',
        stock_name: 'Foo Tech',
        isin: 'INE000000001',
        quantity: 100,
        current_value: 100_000,
      },
    ];
    plan.computed.allocation = {
      investor_risk_band: 'Moderate',
      strategic_allocation: { equity: 50, debt: 35, gold: 10, cash: 5 },
      strategic_equity_split: { large: 65, mid: 20, small: 15 },
      tactical_regime_score: 0,
      tactical_regime_label: 'Neutral',
      signal_breakdown: {
        valuation: { score: 0, reason: '' },
        trend: { score: 0, reason: '' },
        breadth: { score: 0, reason: '' },
        flows: { score: 0, reason: '' },
        macro: { score: 0, reason: '' },
        external: { score: 0, reason: '' },
      },
      recommended_allocation: { equity: 50, debt: 35, gold: 10, cash: 5 },
      recommended_equity_split: { large: 65, mid: 20, small: 15 },
      debt_duration_stance: 'neutral',
      sector_theme_views: { overweight: [], underweight: [] },
      rebalancing_actions: [],
      warnings: [],
    };
    const r = scoreItemForPlan(
      {
        id: 'n-isin',
        title: 'Foo Tech earnings',
        summary: '...',
        sectors: [],
        isins: ['INE000000001'],
        asset_class: 'equity',
        published_at: new Date().toISOString(),
      },
      plan,
    );
    expect(r.relevance).toBeGreaterThan(0);
    expect(r.rationale).toContain('direct holding');
  });
});
