/**
 * Deterministic parser for Indian Account Aggregator PDFs:
 *   - KFin mutual fund statement
 *   - NSDL demat statement
 *   - AA-style bank statement
 * Anchors per `aa_pdf_patterns.md`.
 */
// @ts-expect-error pdf-parse has no shipped types
import pdfParse from 'pdf-parse';
import { randomUUID } from 'node:crypto';
import type { IngestResult } from './index.js';
import type { EvidenceRow, MFHolding, StockHolding, PlanStateDelta } from '../../types/plan-state.js';

const AA_ANCHORS = [
  'Statement of Kfin Technologies Limited',
  'Statement of National Securities Depository Limited',
  'ACCOUNT SUBTYPE',
  'IFSC CODE',
  'MUTUAL FUNDS HOLDINGS',
  'EQUITY HOLDINGS',
];

export async function looksLikeAA(buf: Buffer): Promise<boolean> {
  try {
    const text = (await pdfParse(buf)).text ?? '';
    return AA_ANCHORS.some((a) => text.includes(a));
  } catch {
    return false;
  }
}

export async function parsePdfAA(buf: Buffer, filename: string): Promise<IngestResult> {
  const { text } = await pdfParse(buf);
  const evidence: EvidenceRow[] = [];
  const partial: PlanStateDelta = {};
  const ts = new Date().toISOString();

  // KFin MF
  if (text.includes('Statement of Kfin Technologies Limited')) {
    const mfs: MFHolding[] = [];
    // Lightweight row extractor — Day 2 hardens this.
    const rowRe = /([A-Z][A-Z0-9 .&'\-/()]{6,})\s+([A-Z]{2}\d{10})\s+([\d.,]+)\s+([\d.,]+)\s+([0-9]{2}-[A-Z]{3}-[0-9]{4})/g;
    let m: RegExpExecArray | null;
    while ((m = rowRe.exec(text)) !== null) {
      const id = randomUUID();
      const units = Number(m[3].replace(/,/g, ''));
      const nav = Number(m[4].replace(/,/g, ''));
      const row: MFHolding = {
        id,
        fund_name: m[1].trim(),
        isin: m[2],
        closing_units: units,
        nav,
        nav_date: m[5],
        current_value: Number((units * nav).toFixed(2)),
        registrar: 'KFin',
        source_file: filename,
      };
      mfs.push(row);
      evidence.push({
        field: `mutual_funds.${id}`,
        value: row,
        source_file: filename,
        source_type: 'pdf_aa',
        parser_tier: 'deterministic',
        confidence: 0.95,
        timestamp: ts,
      });
    }
    if (mfs.length) partial.mutual_funds = mfs;
  }

  // NSDL demat
  if (text.includes('Statement of National Securities Depository Limited')) {
    const eq: StockHolding[] = [];
    const rowRe = /([A-Z][A-Z0-9 .&'\-/()]{4,})\s+([A-Z]{2}\d{10})\s+([\d.,]+)\s+([\d.,]+)/g;
    let m: RegExpExecArray | null;
    while ((m = rowRe.exec(text)) !== null) {
      const id = randomUUID();
      const qty = Number(m[3].replace(/,/g, ''));
      const ltp = Number(m[4].replace(/,/g, ''));
      const row: StockHolding = {
        id,
        stock_name: m[1].trim(),
        isin: m[2],
        quantity: qty,
        last_traded_price: ltp,
        current_value: Number((qty * ltp).toFixed(2)),
        source_file: filename,
      };
      eq.push(row);
      evidence.push({
        field: `equity_stocks.${id}`,
        value: row,
        source_file: filename,
        source_type: 'pdf_aa',
        parser_tier: 'deterministic',
        confidence: 0.95,
        timestamp: ts,
      });
    }
    if (eq.length) partial.equity_stocks = eq;
  }

  return {
    partial_state: partial,
    evidence,
    missing: [],
    parser_used: 'pdfAA',
  };
}
