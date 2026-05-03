/**
 * Text-input LLM extraction. Wraps multimodalExtract for backwards
 * compatibility with the existing CSV / XLSX / DOCX / text parsers — they
 * all flatten the input to text first and then call here. Multi-model
 * (Claude → GPT-4o fallback) lives inside multimodalExtract.
 */
import type { EvidenceRow, PlanStateDelta } from '../../types/plan-state.js';
import { multimodalExtract } from './multimodalExtract.js';

export async function llmExtract(args: {
  text: string;
  source_type: EvidenceRow['source_type'];
  filename?: string;
  hint?: string;
}): Promise<{ partial_state: PlanStateDelta; evidence: EvidenceRow[]; missing: string[] }> {
  const result = await multimodalExtract({
    kind: 'text',
    text: args.text,
    sourceType: args.source_type,
    filename: args.filename,
    hint: args.hint,
  });
  // Stamp source_file on every evidence row so the chat shows where each
  // value came from.
  return {
    partial_state: result.partial_state,
    evidence: result.evidence.map((e) => ({ ...e, source_file: args.filename ?? null })),
    missing: result.missing,
  };
}
