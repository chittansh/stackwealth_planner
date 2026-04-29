import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';
import type { EvidenceRow } from '../../types/plan-state.js';

export async function parseText(args: {
  text: string;
  source_type: 'user' | 'transcript' | 'md';
  filename?: string;
}): Promise<IngestResult> {
  const map: Record<typeof args.source_type, EvidenceRow['source_type']> = {
    user: 'user',
    transcript: 'transcript',
    md: 'md',
  };
  const result = await llmExtract({
    text: args.text,
    source_type: map[args.source_type],
    filename: args.filename,
  });
  return { ...result, parser_used: `text:${args.source_type}+llm` };
}
