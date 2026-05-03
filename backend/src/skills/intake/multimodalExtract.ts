/**
 * Multi-model canonical-schema extractor.
 *
 * Strategy:
 *   1. Try Claude Sonnet (best at structured JSON + Indian context).
 *   2. If the result is empty / weak, try GPT-4o.
 *   3. Pick the result with more populated fields and higher mean confidence.
 *
 * Accepts either text input or a binary document (PDF / image) — both major
 * providers support native PDF + image input now, so we skip the lossy
 * "OCR-then-re-extract" two-pass that the original parsers used.
 */

import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';
import type { EvidenceRow, PlanStateDelta } from '../../types/plan-state.js';

// ── Schema prompt ───────────────────────────────────────────────────────

const EXTRACTION_INSTRUCTIONS = `You extract structured Indian household financial-planning data from the input.

Return ONLY a JSON object of this shape (no prose, no code fences):

{
  "partial_state": {
    "personal_details": { "full_name"?, "date_of_birth"?, "marital_status"?, "dependents"?, "city_of_residence"?, "city_type"?: "Metro" | "Non-metro", "occupation"?, "retirement_age_target"? },
    "income_details": { "client_salary_in_hand"?, "spouse_salary_in_hand"?, "client_business_income"?, "spouse_business_income"?, "client_rental_income"?, "client_other_income"? },
    "monthly_expenses": { "rent_or_emi"?, "household_expenses"?, "groceries"?, "utilities"?, "school_fees"?, "insurance_premium"?, "medical"?, "travel_or_lifestyle"?, "sip_investments"?, "other_emis"? },
    "monthly_investments": { "mutual_fund_sip"?, "nps"?, "ppf"?, "rd"?, "direct_equity"?, "insurance_premium"?, "other"? },
    "liquid_capital": { "savings_account_balance"?, "idle_cash_for_investment"?, "fd_breakable_for_investment"?, "bonus_expected_for_investment"? },
    "loans_liabilities": {
      "home_loan"?: { "outstanding_amount"?, "emi"?, "interest_rate"?, "tenure_left"? },
      "car_loan"?: { ... },
      "personal_loan"?: { ... },
      "credit_card_dues"?: { ... }
    },
    "insurance_details": {
      "term_plan"?: { "company"?, "cover_amount"?, "annual_premium"? },
      "health_insurance"?: { ... },
      "family_floater"?: { ... },
      "ulip_or_endowment"?: { ... }
    },
    "mutual_funds"?: [ { "fund_name", "isin"?, "current_value", "closing_units"?, "nav"?, "nav_date"?, "registrar"?, "sip_amount"? } ],
    "equity_stocks"?: [ { "stock_name", "isin"?, "quantity", "current_value", "last_traded_price"? } ],
    "fixed_income"?: [ { "instrument": "FD"|"RD"|"PPF"|"EPF"|"Bonds"|"NPS", "invested_amount"?, "current_value"?, "maturity_date"? } ],
    "financial_goals"?: [ { "goal_name", "kind": "retirement"|"child_education"|"child_marriage"|"house_purchase"|"foreign_travel"|"other", "target_year"?, "target_amount"?, "current_allocated_amount"?, "periodic_contribution"?, "contribution_frequency"?: "monthly"|"annual", "priority"?: "essential"|"important"|"aspirational" } ]
  },
  "evidence": [
    { "field": "<canonical dotted path>", "value": <value>, "confidence": 0.0..1.0, "evidence_quote": "<verbatim short span from the source that supports this value>" }
  ],
  "missing": [ "<canonical paths still missing for downstream planning>" ]
}

Hard rules:
- Currency: amounts in INR (₹). Convert any other currency. Numbers as plain JSON numbers (no commas, no symbols).
- Monthly fields are MONTHLY (₹/month). Annual fields are ANNUAL.
- Dates: DD-MM-YYYY.
- city_type: Mumbai/Delhi/Bengaluru/Chennai/Kolkata/Hyderabad/Pune/Ahmedabad → "Metro", else "Non-metro".
- Never fabricate. If unknown, omit the field and add its canonical path to "missing".
- Every value must be backed by a verbatim short "evidence_quote" from the input. No quote → omit the field.
- If you genuinely cannot extract anything, return { "partial_state": {}, "evidence": [], "missing": ["entire_document_unparseable"] }.`;

// ── Result shape ────────────────────────────────────────────────────────

export type ExtractionResult = {
  partial_state: PlanStateDelta;
  evidence: EvidenceRow[];
  missing: string[];
  parser_used: string;
};

// ── Lazy clients ────────────────────────────────────────────────────────

let _anth: Anthropic | null = null;
function anthropic() {
  if (!_anth) _anth = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  return _anth;
}

let _openai: OpenAI | null = null;
function openai() {
  if (!_openai) _openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  return _openai;
}

// ── Public API ──────────────────────────────────────────────────────────

export type ExtractionInput =
  | { kind: 'text'; text: string; sourceType: EvidenceRow['source_type']; filename?: string; hint?: string }
  | { kind: 'pdf'; bytes: Buffer; sourceType: EvidenceRow['source_type']; filename: string; hint?: string }
  | { kind: 'image'; bytes: Buffer; mime: string; sourceType: EvidenceRow['source_type']; filename: string; hint?: string };

export async function multimodalExtract(input: ExtractionInput): Promise<ExtractionResult> {
  // First pass: Claude — strong on structured JSON + India context.
  const claudeOut = await tryClaude(input);

  if (isStrongResult(claudeOut)) {
    return finalize(claudeOut, input.sourceType, input.kind, 'claude');
  }

  // Weak / empty Claude result — try OpenAI as a second opinion.
  if (process.env.OPENAI_API_KEY) {
    const openaiOut = await tryOpenAI(input);
    const winner = chooseBetter(claudeOut, openaiOut);
    return finalize(
      winner,
      input.sourceType,
      input.kind,
      winner === openaiOut ? 'openai' : 'claude+openai-tied',
    );
  }

  return finalize(claudeOut, input.sourceType, input.kind, 'claude-weak');
}

// ── Claude ──────────────────────────────────────────────────────────────

async function tryClaude(input: ExtractionInput): Promise<RawResult> {
  const model = process.env.PLANNER_MODEL ?? 'claude-sonnet-4-6';
  try {
    // The 'document' content type isn't in the public Anthropic SDK union yet
    // even though the API supports it natively. Build as a loose array and
    // cast at the message boundary.
    const content: unknown[] = [];

    if (input.kind === 'text') {
      content.push({
        type: 'text',
        text: `${input.hint ? `[hint: ${input.hint}]\n\n` : ''}Extract from this:\n\n${input.text.slice(0, 180_000)}`,
      });
    } else if (input.kind === 'pdf') {
      content.push({
        type: 'document',
        source: {
          type: 'base64',
          media_type: 'application/pdf',
          data: input.bytes.toString('base64'),
        },
      });
      content.push({ type: 'text', text: input.hint ?? 'Extract financial data from this PDF.' });
    } else {
      content.push({
        type: 'image',
        source: {
          type: 'base64',
          media_type: input.mime as 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif',
          data: input.bytes.toString('base64'),
        },
      });
      content.push({ type: 'text', text: input.hint ?? 'Extract financial data from this image.' });
    }

    const resp = await anthropic().messages.create({
      model,
      max_tokens: 6000,
      temperature: 0.1,
      system: EXTRACTION_INSTRUCTIONS,
      messages: [{ role: 'user', content: content as Anthropic.MessageParam['content'] }],
    });

    const text = resp.content
      .filter((b) => b.type === 'text')
      .map((b) => (b as { type: 'text'; text: string }).text)
      .join('');

    return parseExtraction(text);
  } catch (err) {
    return { partial_state: {}, evidence: [], missing: [`claude_failed:${(err as Error).message}`] };
  }
}

// ── OpenAI ──────────────────────────────────────────────────────────────

async function tryOpenAI(input: ExtractionInput): Promise<RawResult> {
  // Use GPT-4o — strong vision + reliable JSON mode.
  try {
    if (input.kind === 'text') {
      const resp = await openai().chat.completions.create({
        model: 'gpt-4o',
        temperature: 0.1,
        response_format: { type: 'json_object' },
        messages: [
          { role: 'system', content: EXTRACTION_INSTRUCTIONS },
          {
            role: 'user',
            content: `${input.hint ? `[hint: ${input.hint}]\n\n` : ''}Extract from this:\n\n${input.text.slice(0, 180_000)}`,
          },
        ],
        max_tokens: 6000,
      });
      return parseExtraction(resp.choices[0]?.message?.content ?? '');
    }

    if (input.kind === 'image') {
      const dataUrl = `data:${input.mime};base64,${input.bytes.toString('base64')}`;
      const resp = await openai().chat.completions.create({
        model: 'gpt-4o',
        temperature: 0.1,
        response_format: { type: 'json_object' },
        messages: [
          { role: 'system', content: EXTRACTION_INSTRUCTIONS },
          {
            role: 'user',
            content: [
              { type: 'text', text: input.hint ?? 'Extract financial data from this image.' },
              { type: 'image_url', image_url: { url: dataUrl, detail: 'high' } },
            ],
          },
        ],
        max_tokens: 6000,
      });
      return parseExtraction(resp.choices[0]?.message?.content ?? '');
    }

    // PDF — upload and reference, then ask
    const file = await openai().files.create({
      file: new File([new Uint8Array(input.bytes)], input.filename || 'doc.pdf', {
        type: 'application/pdf',
      }),
      purpose: 'user_data',
    });
    try {
      const resp = await openai().chat.completions.create({
        model: 'gpt-4o',
        temperature: 0.1,
        response_format: { type: 'json_object' },
        messages: [
          { role: 'system', content: EXTRACTION_INSTRUCTIONS },
          {
            role: 'user',
            content: [
              { type: 'text', text: input.hint ?? 'Extract financial data from this PDF.' },
              // OpenAI accepts file references via the file id in the new content type
              {
                type: 'file',
                file: { file_id: file.id },
              } as unknown as { type: 'file'; file: { file_id: string } },
            ] as unknown as OpenAI.Chat.Completions.ChatCompletionContentPart[],
          },
        ],
        max_tokens: 6000,
      });
      return parseExtraction(resp.choices[0]?.message?.content ?? '');
    } finally {
      // Best-effort cleanup so we don't pile up uploaded files.
      openai().files.del(file.id).catch(() => undefined);
    }
  } catch (err) {
    return { partial_state: {}, evidence: [], missing: [`openai_failed:${(err as Error).message}`] };
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────

type RawResult = {
  partial_state: PlanStateDelta;
  evidence: { field: string; value: unknown; confidence?: number; evidence_quote?: string }[];
  missing: string[];
};

function parseExtraction(text: string): RawResult {
  const cleaned = stripFence(text).trim();
  try {
    const parsed = JSON.parse(cleaned);
    return {
      partial_state: parsed.partial_state ?? {},
      evidence: parsed.evidence ?? [],
      missing: parsed.missing ?? [],
    };
  } catch {
    return { partial_state: {}, evidence: [], missing: ['llm_extract_parse_failed'] };
  }
}

function stripFence(s: string): string {
  const m = s.match(/```(?:json)?\s*([\s\S]+?)\s*```/);
  return m ? m[1] : s;
}

function isStrongResult(r: RawResult): boolean {
  // "Strong" = at least one populated section and at least one evidence row
  // with a verbatim quote and decent confidence.
  const sectionHasData = (v: unknown): boolean =>
    v !== null &&
    v !== undefined &&
    !(typeof v === 'object' && Object.keys(v as object).length === 0) &&
    !(Array.isArray(v) && v.length === 0);
  const populated = Object.values(r.partial_state ?? {}).some(sectionHasData);
  const goodEvidence = (r.evidence ?? []).some(
    (e) => (e.confidence ?? 0) >= 0.6 && typeof e.evidence_quote === 'string' && e.evidence_quote.length > 0,
  );
  return populated && goodEvidence;
}

function chooseBetter(a: RawResult, b: RawResult): RawResult {
  const score = (r: RawResult) =>
    Object.values(r.partial_state ?? {}).filter((v) => v !== null && v !== undefined).length +
    (r.evidence ?? []).reduce((s, e) => s + (e.confidence ?? 0), 0);
  return score(b) > score(a) ? b : a;
}

function finalize(
  raw: RawResult,
  sourceType: EvidenceRow['source_type'],
  kind: ExtractionInput['kind'],
  parserUsed: string,
): ExtractionResult {
  const ts = new Date().toISOString();
  const evidence: EvidenceRow[] = (raw.evidence ?? []).map((e) => ({
    field: e.field,
    value: e.value,
    source_file: null,
    source_type: sourceType,
    parser_tier: 'llm',
    confidence: e.confidence ?? 0.5,
    evidence_quote: e.evidence_quote ?? null,
    timestamp: ts,
  }));
  return {
    partial_state: raw.partial_state ?? {},
    evidence,
    missing: raw.missing ?? [],
    parser_used: `${kind}+${parserUsed}`,
  };
}
