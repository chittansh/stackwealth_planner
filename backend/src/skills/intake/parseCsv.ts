import Papa from 'papaparse';
import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';

export async function parseCsv(buf: Buffer, filename: string): Promise<IngestResult> {
  const csv = buf.toString('utf8');
  const parsed = Papa.parse<Record<string, string>>(csv, { header: true, skipEmptyLines: true });
  const sample = JSON.stringify(parsed.data.slice(0, 50), null, 2);
  const result = await llmExtract({
    text: `[csv_headers=${parsed.meta.fields?.join(', ') ?? ''}]\n\nFirst 50 rows:\n${sample}`,
    source_type: 'csv',
    filename,
  });
  return { ...result, parser_used: 'csv+llm' };
}
