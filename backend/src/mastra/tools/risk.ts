import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { assess } from '../../skills/risk/index.js';

export const riskAssessTool = createTool({
  id: 'risk.assess',
  description:
    'Compute the 3-part risk profile (Capacity, Need, Willingness) and the reconciled recommended_score. Required before allocate / tax / montecarlo.',
  inputSchema: z.object({
    household_id: z.string(),
    willingness: z
      .object({
        volatility_reaction: z.enum(['sell_everything', 'sell_some', 'hold_steady', 'buy_more']).optional(),
        risk_return_tradeoff: z.enum(['A', 'B', 'C', 'D']).optional(),
        max_tolerable_loss: z.enum(['0', '10', '20', '30', '>30']).optional(),
      })
      .optional(),
  }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => assess(context),
});
