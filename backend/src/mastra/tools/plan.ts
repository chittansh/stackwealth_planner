/**
 * Plan mutation tools — direct edits to PlanState via the deltas pipeline.
 * Each tool call enforces source priority and recomputes computed.* downstream.
 */
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

import { applySet, applyAdd, applyRemove, applyAssumption } from '../../skills/scenario/index.js';

export const planSetTool = createTool({
  id: 'plan.set',
  description: 'Set a single canonical field on PlanState (e.g. personal_details.date_of_birth).',
  inputSchema: z.object({
    household_id: z.string(),
    path: z.string(),
    value: z.unknown(),
    source_type: z
      .enum(['user', 'transcript', 'pdf_aa', 'pdf_generic', 'xlsx', 'csv', 'docx', 'md', 'image', 'audio', 'inferred', 'derived'])
      .default('user'),
  }),
  outputSchema: z.object({ ok: z.boolean(), updated_path: z.string() }),
  execute: async ({ context }) => applySet(context),
});

export const planAddTool = createTool({
  id: 'plan.add',
  description: 'Append a row to a list-typed canonical section (income, expenses, events, holdings, goals).',
  inputSchema: z.object({
    household_id: z.string(),
    path: z.string(),
    row: z.unknown(),
    source_type: z
      .enum(['user', 'transcript', 'pdf_aa', 'pdf_generic', 'xlsx', 'csv', 'docx', 'md', 'image', 'audio', 'inferred', 'derived'])
      .default('user'),
  }),
  outputSchema: z.object({ ok: z.boolean(), id: z.string() }),
  execute: async ({ context }) => applyAdd(context),
});

export const planRemoveTool = createTool({
  id: 'plan.remove',
  description: 'Remove a row by id from a list-typed canonical section.',
  inputSchema: z.object({
    household_id: z.string(),
    path: z.string(),
    id: z.string(),
  }),
  outputSchema: z.object({ ok: z.boolean() }),
  execute: async ({ context }) => applyRemove(context),
});

export const planAssumptionTool = createTool({
  id: 'plan.assumption',
  description: 'Set an assumption value (per-person DOB / life expectancy / retirement age, growth rates, taxes, inflation).',
  inputSchema: z.object({
    household_id: z.string(),
    path: z.string(), // e.g. "assumptions.persons.0.retirement_age"
    value: z.unknown(),
  }),
  outputSchema: z.object({ ok: z.boolean(), updated_path: z.string() }),
  execute: async ({ context }) => applyAssumption(context),
});
