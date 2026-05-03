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

  const flat = flattenWorkbook(wb);
  const hint = matched
    ? `Excel matches the "${matched.name}" template; sheets: ${sheetNames.join(', ')}.`
    : `Excel with ${sheetNames.length} sheet(s): ${sheetNames.join(', ')}.`;

  const result = await llmExtract({
    text: flat,
    source_type: 'xlsx',
    filename,
    hint,
  });
  return { ...result, parser_used: matched ? `xlsx:${matched.name}+multimodal` : 'xlsx+multimodal' };
}

function flattenWorkbook(wb: XLSX.WorkBook): string {
  const out: string[] = [];
  for (const name of wb.SheetNames) {
    const sheet = wb.Sheets[name];
    const csv = XLSX.utils.sheet_to_csv(sheet, { strip: true, blankrows: false });
    if (!csv.trim()) continue;
    // Cap each sheet to the first 400 lines so a giant ledger doesn't blow context.
    const lines = csv.split('\n');
    const truncated = lines.length > 400;
    const body = (truncated ? lines.slice(0, 400) : lines).join('\n');
    out.push(`### Sheet: ${name}${truncated ? ` (first 400 of ${lines.length} rows)` : ''}\n${body}`);
  }
  return out.join('\n\n');
}
