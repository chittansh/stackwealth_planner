import Papa from 'papaparse';
import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';

export async function parseCsv(buf: Buffer, filename: string): Promise<IngestResult> {
  const csv = buf.toString('utf8');
  const parsed = Papa.parse<Record<string, string>>(csv, { header: true, skipEmptyLines: true });
  const headers = parsed.meta.fields ?? [];
  const rows = parsed.data;

  // Pretty-print as a markdown-ish table so the LLM sees structure clearly.
  const sample = rows.slice(0, 200);
  const flat = [
    headers.join(' | '),
    headers.map(() => '---').join(' | '),
    ...sample.map((r) => headers.map((h) => String(r[h] ?? '')).join(' | ')),
  ].join('\n');
  const note =
    rows.length > sample.length
      ? `\n\n(Showing first 200 of ${rows.length} rows.)`
      : '';

  const hint = `CSV with columns: ${headers.join(', ')}.`;
  const result = await llmExtract({
    text: `${flat}${note}`,
    source_type: 'csv',
    filename,
    hint,
  });
  return { ...result, parser_used: 'csv+multimodal' };
}
