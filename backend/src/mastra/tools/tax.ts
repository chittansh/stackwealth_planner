import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { harvest } from '../../skills/tax/index.js';

export const taxHarvestTool = createTool({
  id: 'tax.harvest',
  description:
    'Compute LTCG/STCG harvest suggestions, loss harvesting, combined impact, and fee-vs-value gates for the current FY. Refuses if risk gate not passed.',
  inputSchema: z.object({ household_id: z.string() }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => harvest(context),
});
