import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

export const newsRelevanceTool = createTool({
  id: 'news.relevance',
  description:
    'Score how relevant each known news item is for a specific household, using sector × direct holdings × MFs × asset-class exposure.',
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
  execute: async () => {
    // Day 5 — relevance scoring. Stub returns empty today.
    return { items: [] };
  },
});
