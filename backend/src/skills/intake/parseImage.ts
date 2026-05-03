/**
 * Image intake — single-pass structured extraction. Sends the image straight
 * to a multimodal model with the canonical schema; tries Claude first then
 * falls back to GPT-4o so screenshots of brokerage statements, salary slips,
 * Zerodha P&L, etc. all extract cleanly without an OCR-then-re-extract dance.
 */
import { multimodalExtract } from './multimodalExtract.js';
import type { IngestResult } from './index.js';

export async function parseImage(buf: Buffer, filename: string, mime: string): Promise<IngestResult> {
  try {
    const result = await multimodalExtract({
      kind: 'image',
      bytes: buf,
      mime,
      sourceType: 'image',
      filename,
    });
    return { ...result, parser_used: `image:${result.parser_used}` };
  } catch (err) {
    return {
      partial_state: {},
      evidence: [],
      missing: [`image_extraction_failed:${(err as Error).message}`],
      parser_used: 'image:failed',
    };
  }
}
