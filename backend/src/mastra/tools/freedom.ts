import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { score } from '../../skills/freedom/index.js';

export const freedomScoreTool = createTool({
  id: 'freedom.score',
  description: 'Compute the 5-pillar Freedom Score (0-100) with city-sensitive insurance logic.',
  inputSchema: z.object({ household_id: z.string() }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => score(context),
});
