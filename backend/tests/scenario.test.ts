import { describe, it, expect } from 'vitest';
import { applySet, applyAdd, confirmField } from '../src/skills/scenario/index.js';
import { emptyPlanState } from '../src/types/plan-state.js';
import { savePlan, getPlan, seedMemory } from '../src/db/client.js';

describe('plan deltas', () => {
  it('applySet writes a value and an evidence row', async () => {
    const plan = emptyPlanState('hh-set');
    seedMemory(plan);
    await savePlan(plan);
    await applySet({
      household_id: 'hh-set',
      path: 'personal_details.full_name',
      value: 'Test User',
      source_type: 'user',
    });
    const after = await getPlan('hh-set');
    expect(after?.personal_details.full_name).toBe('Test User');
    expect(after?.evidence.some((e) => e.field === 'personal_details.full_name')).toBe(true);
  });

  it('applyAdd appends a row with an id', async () => {
    const plan = emptyPlanState('hh-add');
    seedMemory(plan);
    await savePlan(plan);
    const r = await applyAdd({
      household_id: 'hh-add',
      path: 'financial_goals',
      row: { goal_name: 'Test goal', kind: 'other', target_year: 2030, target_amount: 100_000 },
      source_type: 'user',
    });
    expect(r.id).toBeTruthy();
    const after = await getPlan('hh-add');
    expect(after?.financial_goals).toHaveLength(1);
  });

  it('confirmField promotes evidence to manual + confidence 1.0', async () => {
    const plan = emptyPlanState('hh-confirm');
    plan.evidence.push({
      field: 'income_details.client_salary_in_hand',
      value: 250_000,
      source_file: 'note.txt',
      source_type: 'user',
      parser_tier: 'llm',
      confidence: 0.6,
      timestamp: new Date().toISOString(),
    });
    plan.missing_fields = ['income_details.client_salary_in_hand'];
    seedMemory(plan);
    await savePlan(plan);

    const r = await confirmField({ household_id: 'hh-confirm', field: 'income_details.client_salary_in_hand' });
    expect(r.ok).toBe(true);
    const after = await getPlan('hh-confirm');
    const ev = after?.evidence.find((e) => e.field === 'income_details.client_salary_in_hand');
    expect(ev?.parser_tier).toBe('manual');
    expect(ev?.confidence).toBe(1.0);
    expect(after?.income_details.client_salary_in_hand).toBe(250_000);
    expect(after?.missing_fields).not.toContain('income_details.client_salary_in_hand');
  });
});
