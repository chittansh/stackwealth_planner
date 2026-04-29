import mammoth from 'mammoth';
import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';

export async function parseDocx(buf: Buffer, filename: string): Promise<IngestResult> {
  const { value: markdown } = await mammoth.convertToMarkdown({ buffer: buf });
  const result = await llmExtract({
    text: markdown,
    source_type: 'docx',
    filename,
  });
  return { ...result, parser_used: 'docx+llm' };
}
