/**
 * Intake tools — universal dispatcher.
 *
 * The agent calls `intake.ingest` for ANY input (file or pasted text). The
 * dispatcher routes to a deterministic parser when the input matches a known
 * signature; otherwise it falls back to an LLM extraction against the
 * canonical schema with per-field confidence + evidence_quote.
 */
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

import { ingest } from '../../skills/intake/index.js';
import { confirmField } from '../../skills/scenario/index.js';

export const intakeIngestTool = createTool({
  id: 'intake.ingest',
  description:
    'Universal intake dispatcher. Accepts a file (PDF, XLSX, CSV, DOCX, MD, TXT, image, audio) or pasted text/transcript and returns a partial PlanState delta with evidence and per-field confidence.',
  inputSchema: z.object({
    household_id: z.string(),
    source: z.union([
      z.object({
        kind: z.literal('file'),
        filename: z.string(),
        mime: z.string(),
        // base64-encoded contents passed in from the upload route
        contents_b64: z.string(),
      }),
      z.object({
        kind: z.literal('text'),
        text: z.string(),
        source_type: z.enum(['user', 'transcript', 'md']).default('user'),
      }),
    ]),
  }),
  outputSchema: z.object({
    partial_state: z.unknown(),
    evidence: z.array(z.unknown()),
    missing: z.array(z.string()),
    parser_used: z.string(),
  }),
  execute: async ({ context }) => {
    return ingest(context);
  },
});

export const intakeConfirmTool = createTool({
  id: 'intake.confirm',
  description:
    'Promote an LLM-extracted (low-confidence) field to confirmed when the user accepts it in chat.',
  inputSchema: z.object({
    household_id: z.string(),
    field: z.string(),
    value: z.unknown(),
    source_id: z.string().optional(),
  }),
  outputSchema: z.object({
    ok: z.boolean(),
  }),
  execute: async ({ context }) => {
    return confirmField({
      household_id: context.household_id,
      field: context.field,
      value: context.value,
    });
  },
});
