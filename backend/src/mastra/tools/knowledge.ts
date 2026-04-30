import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { retrieve } from '../../skills/knowledge/index.js';

export const knowledgeRetrieveTool = createTool({
  id: 'knowledge.retrieve',
  description:
    'Retrieve top-K chunks from the firm knowledge base. Returns chunk text + filename + heading + similarity score for inline citation.',
  inputSchema: z.object({
    org_id: z.string().default('demo'),
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
  execute: async ({ context }) => retrieve(context),
});
