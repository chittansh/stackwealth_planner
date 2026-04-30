import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { relevanceForHousehold } from '../../skills/news/index.js';

export const newsRelevanceTool = createTool({
  id: 'news.relevance',
  description:
    'Score how relevant each news item in the demo store is for a specific household, using sector × direct holdings × asset-class exposure.',
  inputSchema: z.object({
    household_id: z.string(),
    top_k: z.number().int().min(1).max(20).default(5),
  }),
  outputSchema: z.object({
    items: z.array(
      z.object({
        news_id: z.string(),
        title: z.string(),
        relevance: z.number(),
        rationale: z.string(),
      }),
    ),
  }),
  execute: async ({ context }) => relevanceForHousehold(context),
});
