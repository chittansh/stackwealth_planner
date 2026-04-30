/**
 * LLM extraction — schema-guided, low-temperature extraction against the
 * canonical PlanState shape. Every leaf field returned must include a
 * `confidence` (0..1) and `evidence_quote` (verbatim span from the input).
 *
 * The validator middleware (Day 6) rejects any extracted value without a
 * matching `evidence_quote` substring in the source text.
 */
import Anthropic from '@anthropic-ai/sdk';
import type { EvidenceRow, PlanStateDelta } from '../../types/plan-state.js';

let _client: Anthropic | null = null;
function client() {
  if (!_client) _client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  return _client;
}

const SYSTEM = `You extract structured Indian household financial-planning data.

Return ONLY a JSON object of shape:

{
  "partial_state": { ...partial PlanState by canonical sections... },
  "evidence": [
    {
      "field": "personal_details.full_name" | "income_details.client_salary_in_hand" | ... ,
      "value": <extracted value>,
      "confidence": 0.0..1.0,
      "evidence_quote": "<verbatim span from the input that supports this value>"
    }
  ],
  "missing": ["<canonical paths still missing for downstream planning>"]
}

Hard rules:
- Currency: amounts in INR (₹). Convert any other currency note in the source. Numbers as plain JSON numbers (no commas, no symbols).
- Dates: DD-MM-YYYY.
- Never fabricate a number. If unknown, omit the field and include its canonical path in "missing".
- Every value must be backed by a verbatim "evidence_quote" from the input. No quote → omit the field.
- Lower temperature thinking. Prefer skipping a value to guessing.

Canonical sections (top-level keys you may use):
  personal_details, income_details, monthly_expenses,
  mutual_funds[], equity_stocks[], fixed_income[], monthly_investments,
  liquid_capital, emergency_fund, loans_liabilities, insurance_details,
  financial_goals[], freedom_score_inputs, assumptions.
`;

export async function llmExtract(args: {
  text: string;
  source_type: EvidenceRow['source_type'];
  filename?: string;
}): Promise<{ partial_state: PlanStateDelta; evidence: EvidenceRow[]; missing: string[] }> {
  const resp = await client().messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 4000,
    temperature: 0.1,
    system: SYSTEM,
    messages: [{ role: 'user', content: args.text.slice(0, 60_000) }],
  });

  const text = resp.content
    .filter((b) => b.type === 'text')
    .map((b) => (b as { type: 'text'; text: string }).text)
    .join('');

  let parsed: { partial_state: PlanStateDelta; evidence: { field: string; value: unknown; confidence: number; evidence_quote: string }[]; missing: string[] };
  try {
    parsed = JSON.parse(stripFence(text));
  } catch {
    return { partial_state: {}, evidence: [], missing: ['llm_extract_parse_failed'] };
  }

  const ts = new Date().toISOString();
  const evidence: EvidenceRow[] = (parsed.evidence ?? []).map((e) => ({
    field: e.field,
    value: e.value,
    source_file: args.filename ?? null,
    source_type: args.source_type,
    parser_tier: 'llm',
    confidence: e.confidence ?? 0.5,
    evidence_quote: e.evidence_quote ?? null,
    timestamp: ts,
  }));

  return {
    partial_state: parsed.partial_state ?? {},
    evidence,
    missing: parsed.missing ?? [],
  };
}

function stripFence(s: string): string {
  const m = s.match(/```(?:json)?\s*([\s\S]+?)\s*```/);
  return m ? m[1] : s;
}
