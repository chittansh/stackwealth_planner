/**
 * Universal intake dispatcher.
 *
 * Detects mime + content signature → routes to a sub-parser. Always returns:
 *   { partial_state, evidence, missing, parser_used }
 *
 * Two-tier extraction:
 *  - Tier 1 deterministic: AA PDFs, known-template XLSX (Stackwealth intake,
 *    freedom score v5, tax harvest v3).
 *  - Tier 2 LLM extraction: anything else, schema-guided, with per-field
 *    confidence + evidence_quote.
 */
import type { PlanStateDelta, EvidenceRow } from '../../types/plan-state.js';
import { parsePdfAA, looksLikeAA } from './parsePdfAA.js';
import { parsePdfGeneric } from './parsePdfGeneric.js';
import { parseXlsx } from './parseXlsx.js';
import { parseCsv } from './parseCsv.js';
import { parseDocx } from './parseDocx.js';
import { parseText } from './parseText.js';
import { parseImage } from './parseImage.js';
import { parseAudio } from './parseAudio.js';

export type IngestInput =
  | {
      household_id: string;
      source: { kind: 'file'; filename: string; mime: string; contents_b64: string };
    }
  | {
      household_id: string;
      source: { kind: 'text'; text: string; source_type: 'user' | 'transcript' | 'md' };
    };

export type IngestResult = {
  partial_state: PlanStateDelta;
  evidence: EvidenceRow[];
  missing: string[];
  parser_used: string;
};

export async function ingest(input: IngestInput): Promise<IngestResult> {
  const { source } = input;

  if (source.kind === 'text') {
    return parseText({ text: source.text, source_type: source.source_type });
  }

  const buf = Buffer.from(source.contents_b64, 'base64');
  const mime = source.mime;
  const filename = source.filename;

  // PDFs
  if (mime === 'application/pdf' || filename.toLowerCase().endsWith('.pdf')) {
    if (await looksLikeAA(buf)) {
      return parsePdfAA(buf, filename);
    }
    return parsePdfGeneric(buf, filename);
  }

  // Excel
  if (
    mime.includes('spreadsheetml') ||
    filename.match(/\.xlsx?$/i)
  ) {
    return parseXlsx(buf, filename);
  }

  // CSV
  if (mime === 'text/csv' || filename.toLowerCase().endsWith('.csv')) {
    return parseCsv(buf, filename);
  }

  // Word
  if (mime.includes('wordprocessingml') || filename.toLowerCase().endsWith('.docx')) {
    return parseDocx(buf, filename);
  }

  // Markdown / plain text
  if (mime.startsWith('text/') || filename.match(/\.(md|markdown|txt)$/i)) {
    return parseText({ text: buf.toString('utf8'), source_type: 'md', filename });
  }

  // Images
  if (mime.startsWith('image/')) {
    return parseImage(buf, filename, mime);
  }

  // Audio / video
  if (mime.startsWith('audio/') || mime.startsWith('video/')) {
    return parseAudio(buf, filename, mime);
  }

  // Unknown → fall back to text
  return parseText({ text: buf.toString('utf8').slice(0, 100_000), source_type: 'md', filename });
}
