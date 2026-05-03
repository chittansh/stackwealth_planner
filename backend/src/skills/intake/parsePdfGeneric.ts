/**
 * Generic PDF parser. Sends the binary directly to a multimodal model so
 * scanned PDFs, complex tables, and image-heavy layouts all extract — none
 * of which pdf-parse handled well. Falls back to pdf-parse text only if the
 * binary path fails (e.g. provider rejects the file size).
 */
import pdfParse from 'pdf-parse';
import { multimodalExtract } from './multimodalExtract.js';
import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';

export async function parsePdfGeneric(buf: Buffer, filename: string): Promise<IngestResult> {
  // Direct PDF → multimodal model (handles text, tables, AND scanned pages).
  try {
    const result = await multimodalExtract({
      kind: 'pdf',
      bytes: buf,
      sourceType: 'pdf_generic',
      filename,
    });
    if (result.evidence.length > 0 || Object.keys(result.partial_state).length > 0) {
      return { ...result, parser_used: `pdfGeneric:${result.parser_used}` };
    }
  } catch {
    /* fall through to text fallback */
  }

  // Last-resort fallback — extract text and ask the text-only path.
  try {
    const { text } = await pdfParse(buf);
    if (text && text.trim().length > 0) {
      const result = await llmExtract({ text, source_type: 'pdf_generic', filename });
      return { ...result, parser_used: 'pdfGeneric:text-fallback' };
    }
  } catch {
    /* ignored */
  }

  return {
    partial_state: {},
    evidence: [],
    missing: ['pdf_extraction_failed'],
    parser_used: 'pdfGeneric:failed',
  };
}
