import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

export const knowledgeRetrieveTool = createTool({
  id: 'knowledge.retrieve',
  description:
    'Retrieve top-K chunks from the firm knowledge base (institutional research, MF policy docs, allocation memos). Returns chunk text + filename for inline citation.',
  inputSchema: z.object({
    org_id: z.string(),
    query: z.string(),
    top_k: z.number().int().min(1).max(10).default(3),
  }),
  outputSchema: z.object({
    chunks: z.array(
      z.object({
        text: z.string(),
        filename: z.string(),
        heading: z.string().optional(),
        score: z.number(),
      }),
    ),
  }),
  execute: async () => {
    // Day 5 — pgvector retrieval. Stub returns empty chunks today.
    return { chunks: [] };
  },
});
