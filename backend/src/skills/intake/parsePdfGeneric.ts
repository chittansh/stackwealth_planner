// @ts-expect-error pdf-parse has no shipped types
import pdfParse from 'pdf-parse';
import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';

export async function parsePdfGeneric(buf: Buffer, filename: string): Promise<IngestResult> {
  const { text } = await pdfParse(buf);
  const result = await llmExtract({
    text,
    source_type: 'pdf_generic',
    filename,
  });
  return { ...result, parser_used: 'pdfGeneric+llm' };
}
