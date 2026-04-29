import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { pin, diff, runMonteCarlo } from '../../skills/scenario/index.js';

export const scenarioPinTool = createTool({
  id: 'scenario.pin',
  description:
    'Pin the current plan as a scenario (Plan A or Plan B). Adds a second curve to the chart and a second headline line.',
  inputSchema: z.object({
    household_id: z.string(),
    label: z.string(),
    mutation: z
      .object({
        ops: z.array(
          z.object({
            path: z.string(),
            op: z.enum(['set', 'add', 'remove']),
            value: z.unknown().optional(),
            row: z.unknown().optional(),
            id: z.string().optional(),
          }),
        ),
      })
      .optional(),
  }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => pin(context),
});

export const scenarioDiffTool = createTool({
  id: 'scenario.diff',
  description: 'Diff two scenarios and return per-field deltas + projection deltas.',
  inputSchema: z.object({
    household_id: z.string(),
    a: z.string(),
    b: z.string(),
  }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => diff(context),
});

export const montecarloRunTool = createTool({
  id: 'montecarlo.run',
  description:
    '2,000-path Monte Carlo. Equity returns ~ N(μ, σ) by risk band; debt+gold+cash deterministic. Outputs P10/P50/P90 freedom-age and per-goal success probability. Refuses if risk gate not passed.',
  inputSchema: z.object({
    household_id: z.string(),
    paths: z.number().int().min(500).max(10_000).default(2000),
  }),
  outputSchema: z.unknown(),
  execute: async ({ context }) => runMonteCarlo(context),
});
