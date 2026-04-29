import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { recommend } from '../../skills/allocate/index.js';

export const allocateRecommendTool = createTool({
  id: 'allocate.recommend',
  description:
    'Strategic + bounded tactical India allocation. Strategic anchor by risk band; tactical overlay from 6 signal blocks (valuation/trend/breadth/flows/macro/external). Refuses if risk gate not passed.',
  inputSchema: z.object({
    household_id: z.string(),
  }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => recommend(context),
});
