import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { project } from '../../skills/cashflow/index.js';

export const cashflowProjectTool = createTool({
  id: 'cashflow.project',
  description: 'Year-by-year cash flow projection + 12-month forward strip + retirement glide path.',
  inputSchema: z.object({
    household_id: z.string(),
    horizon_years: z.number().int().min(5).max(80).default(45),
  }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => project(context),
});
