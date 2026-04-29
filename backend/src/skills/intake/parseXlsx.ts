import * as XLSX from 'xlsx';
import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';

const KNOWN_TEMPLATES: { name: string; required_sheets: string[] }[] = [
  {
    name: 'stackwealth_intake',
    required_sheets: [
      '1_Personal_Details',
      '2_Income_Details',
      '3_Monthly_Expenses',
      '10_Financial_Goals',
    ],
  },
  {
    name: 'freedom_score_v5',
    required_sheets: ['🏆 Dashboard', '📥 Inputs'],
  },
  {
    name: 'tax_harvesting_v3',
    required_sheets: ['Dashboard', 'Gain Harvesting', 'Loss Harvesting'],
  },
];

export async function parseXlsx(buf: Buffer, filename: string): Promise<IngestResult> {
  const wb = XLSX.read(buf, { type: 'buffer' });
  const sheetNames = wb.SheetNames;

  const matched = KNOWN_TEMPLATES.find((t) => t.required_sheets.every((s) => sheetNames.includes(s)));

  if (matched) {
    // Day 2 — implement deterministic per-template extractors. For now, fall through to LLM
    // with a hint about which template was matched.
    const flat = flattenWorkbook(wb);
    const result = await llmExtract({
      text: `[matched_template=${matched.name}]\n\n${flat}`,
      source_type: 'xlsx',
      filename,
    });
    return { ...result, parser_used: `xlsx:${matched.name}+llm` };
  }

  const flat = flattenWorkbook(wb);
  const result = await llmExtract({ text: flat, source_type: 'xlsx', filename });
  return { ...result, parser_used: 'xlsx+llm' };
}

function flattenWorkbook(wb: XLSX.WorkBook): string {
  const out: string[] = [];
  for (const name of wb.SheetNames) {
    const sheet = wb.Sheets[name];
    const csv = XLSX.utils.sheet_to_csv(sheet, { strip: true, blankrows: false });
    if (!csv.trim()) continue;
    out.push(`### Sheet: ${name}\n${csv.split('\n').slice(0, 200).join('\n')}`);
  }
  return out.join('\n\n');
}
