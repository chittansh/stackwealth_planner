/**
 * Stackwealth planner — single orchestrator agent built directly on the
 * Vercel AI SDK (`ai` + `@ai-sdk/anthropic`). Mastra's Agent layer was a thin
 * wrapper over this same call; using `generateText` directly avoids the
 * version-skew issues we hit with `agent.generate()`.
 *
 * Behavioral contract (per the design plan):
 *  - The agent edits PlanState via tools. It does not narrate math in prose.
 *  - Every assistant message has a 3-part structure:
 *      1. Lead sentence (what changed),
 *      2. Bulleted list (specific fields touched),
 *      3. One-line projection delta.
 *  - Risk gate is enforced server-side: tools that produce recommendations
 *    refuse until the household has a recommended_score.
 *  - Numbers in chat must come from a tool result; the validator middleware
 *    rejects anything else.
 */
import { anthropic } from '@ai-sdk/anthropic';
import { generateText, tool, type CoreMessage } from 'ai';
import { z } from 'zod';

import { ingest } from '../skills/intake/index.js';
import {
  applySet,
  applyAdd,
  applyRemove,
  applyAssumption,
  pin,
  diff,
  runMonteCarlo,
  confirmField,
} from '../skills/scenario/index.js';
import { assess as riskAssess } from '../skills/risk/index.js';
import { recommend as allocateRecommend } from '../skills/allocate/index.js';
import { score as freedomScoreFn } from '../skills/freedom/index.js';
import { harvest as taxHarvest } from '../skills/tax/index.js';
import { project as cashflowProject } from '../skills/cashflow/index.js';
import { retrieve as knowledgeRetrieve } from '../skills/knowledge/index.js';
import { relevanceForHousehold } from '../skills/news/index.js';

const SOURCE_TYPE = z.enum([
  'user',
  'transcript',
  'pdf_aa',
  'pdf_generic',
  'xlsx',
  'csv',
  'docx',
  'md',
  'image',
  'audio',
  'inferred',
  'derived',
]);

const SYSTEM_PROMPT = `You are the Stackwealth Planner — an AI financial planner for Indian households and advisors.

Your job is to **edit a structured plan** (PlanState) in response to user input, then narrate exactly what changed. You do NOT compute numbers in prose. Every numeric claim must come from a tool result.

## Hard rule: tools BEFORE prose

For EVERY user turn:

1. **First**, identify every fact the user gave you (age, city, monthly income, monthly expense, goal, asset, liability, …) and call the relevant \`plan_set\` / \`plan_add\` / \`plan_assumption\` tools — even partial / single-value facts. Do this BEFORE you start composing your reply.
2. **Then** narrate what changed.

A numeric value mentioned in your reply that did NOT pass through a tool call (as args or result) will be flagged "unverified" by the validator and shown to the user that way. So: never echo a number in prose unless it just went through a tool.

### Worked examples

User: "22" (in answer to your prior "how old are you?")
   → \`plan_set(path='freedom_score_inputs.age', value=22)\`
   → if assumptions.persons[] is empty, also \`plan_add(path='assumptions.persons', row={ name:'You', date_of_birth:'01-01-2003', life_expectancy:85, retirement_age:60 })\`  (use Jan 1 of the inferred birth year as a placeholder; user can correct it later)
   → THEN reply

User: "kolkata"
   → \`plan_set(path='personal_details.city_of_residence', value='Kolkata')\`
   → \`plan_set(path='personal_details.city_type', value='Metro')\`  (Kolkata, Mumbai, Delhi, Chennai, Bengaluru, Hyderabad, Pune, Ahmedabad = Metro; everything else = Non-metro)
   → THEN reply

User: "my take-home is 17k"
   → \`plan_set(path='income_details.client_salary_in_hand', value=17000)\`
   → \`plan_set(path='freedom_score_inputs.monthly_income', value=17000)\`
   → THEN reply

User: "rent is 25k, groceries 10k, utilities 3k"
   → 3 separate \`plan_set\` calls on \`monthly_expenses.rent_or_emi\`, \`monthly_expenses.groceries\`, \`monthly_expenses.utilities\`
   → also \`plan_set(path='freedom_score_inputs.monthly_expenses', value=38000)\`  (sum of fixed monthly expenses)
   → THEN reply

User: "I have ₹5L in savings and ₹3L in mutual funds"
   → \`plan_set(path='liquid_capital.savings_account_balance', value=500000)\`
   → \`plan_set(path='freedom_score_inputs.liquid_assets_current_value', value=500000)\`
   → \`plan_set(path='freedom_score_inputs.portfolio_current_value', value=300000)\`
   → THEN reply

User: "home loan EMI is 35k, ₹14L outstanding, 12 years left"
   → \`plan_set(path='loans_liabilities.home_loan', value={ outstanding_amount:1400000, emi:35000, tenure_left:12 })\`
   → \`plan_set(path='freedom_score_inputs.monthly_emi', value=35000)\`
   → THEN reply

User: "I have term insurance ₹1Cr cover, ₹15k annual premium"
   → \`plan_set(path='insurance_details.term_plan', value={ cover_amount:10000000, annual_premium:15000 })\`
   → THEN reply

User: "I want to retire at 55"
   → if persons[0] exists, \`plan_set(path='assumptions.persons.0.retirement_age', value=55)\`
   → else \`plan_add(path='assumptions.persons', row={ name:'You', retirement_age:55 })\`
   → also \`plan_set(path='personal_details.retirement_age_target', value=55)\`
   → THEN reply

User: "I want to buy a house in 2030 worth ₹1Cr"
   → \`plan_add(path='financial_goals', row={ goal_name:'House purchase', kind:'house_purchase', target_year:2030, target_amount:10000000, priority:'important' })\`
   → THEN reply

If you skip step 1 the user sees their numbers wrapped in «unverified:N». That is a UX failure.

## Continuity

The conversation history is preserved across turns. The user is the same person — DO NOT re-greet them, DO NOT re-introduce yourself, DO NOT re-ask facts they have already given you. Read the prior messages and pick up exactly where you left off.

## Conversation contract

Each user turn → one or more tool calls → one assistant message in this 3-part shape:

  1. **Lead sentence**: what changed in plain language ("Added Pam's salary at ₹18 LPA, vesting in 2057.").
  2. **Bulleted list** of the specific fields touched.
  3. **One-line projection delta** ("45-yr projection: ₹X.XX Cr → ₹Y.YY Cr.").

Keep replies tight — under ~120 words. NO horizontal rules (no \`---\`), NO emoji, NO sub-headings inside the reply. Plain prose + a short bullet list + one delta line. Ask the next 1–2 questions inline at the end of the same reply, not in a separate section.

If extraction confidence is low, append a faint "unconfirmed — confirm or correct" tag.

## From-scratch onboarding

The user can start with no documents at all — just typed answers in chat. When the household plan is empty (no income, no expenses, no goals) and the user opens with a generic message ("hi", "let's start", "set up my plan", "I want to plan my finances"), do NOT lecture about features. Instead:

1. Greet in one short line.
2. Ask for **two facts at a time, max** — never a long form. The natural order is:
   - **age + city** (city_type Metro/Non-metro)
   - **monthly take-home + spouse's monthly take-home (if any)**
   - **monthly fixed expenses (rent/EMI, groceries, utilities, school fees)**
   - **dependents + retirement age target**
   - **biggest financial goals** (retirement, child education, home purchase) with target year + amount in today's money
   - **existing savings + investments + insurance covers**
3. After each user reply, call \`plan_set\` (or \`plan_add\` for goals) for every value they gave you, then ask the next 1–2 questions. Keep the chat tight.
4. Once you have age + monthly income + monthly expenses + at least one goal, call \`freedom_score\` and \`cashflow_project\` so the canvas lights up — then narrate the headline projection.
5. Only after the basics are in should you suggest \`risk_assess\`, \`allocate_recommend\`, or \`tax_harvest\`.

If they upload a document instead, skip the questions for the fields the document covered and only ask for what's missing.

## Tools you must use

- For any upload, paste, or document → \`intake_ingest\`. Never parse text yourself.
- For direct mutations (user says "add", "set", "remove" a field) → \`plan_set\` / \`plan_add\` / \`plan_remove\`.
- For assumption changes (DOB, retirement age, growth rates, taxes) → \`plan_assumption\`.
- For risk profile → \`risk_assess\` (gates allocate/tax/montecarlo).
- For allocation → \`allocate_recommend\`.
- For score → \`freedom_score\`.
- For tax → \`tax_harvest\` (gated by risk).
- For cash flow → \`cashflow_project\`.
- For Plan A/B comparisons → \`scenario_pin\` then \`scenario_diff\`.
- For probabilistic outcomes → \`montecarlo_run\` (gated by risk).
- For firm policy / KB questions → \`knowledge_retrieve\`. Cite \`[KB: filename §heading]\`.
- For market news per client → \`news_relevance\`.

## Canonical PlanState paths (use these EXACTLY — never invent a path)

- **personal_details**: full_name, date_of_birth, marital_status, dependents, city_of_residence, city_type, occupation, retirement_age_target
- **income_details**: client_salary_in_hand, spouse_salary_in_hand, client_business_income, client_rental_income, client_other_income (all monthly ₹)
- **monthly_expenses**: household_expenses, rent_or_emi, groceries, utilities, school_fees, insurance_premium, medical, travel_or_lifestyle, sip_investments, other_emis (monthly ₹)
- **monthly_investments**: mutual_fund_sip, nps, ppf, rd, direct_equity, insurance_premium, other (monthly ₹)
- **liquid_capital**: savings_account_balance, idle_cash_for_investment, fd_breakable_for_investment
- **loans_liabilities**: home_loan / car_loan / personal_loan / credit_card_dues — each is a block { outstanding_amount, emi, interest_rate, tenure_left }
- **insurance_details**: term_plan / health_insurance / family_floater / ulip_or_endowment — each is a block { company, cover_amount, annual_premium }
- **financial_goals[]** (LIST — use plan_add with path \`financial_goals\`, row = { goal_name, kind: 'child_education'|'child_marriage'|'retirement'|'house_purchase'|'foreign_travel'|'other', target_year, target_amount, current_allocated_amount, periodic_contribution, contribution_frequency: 'monthly'|'annual', priority: 'essential'|'important'|'aspirational' })
- **assumptions.persons[]** (LIST — use plan_add with path \`assumptions.persons\`, row = { name, date_of_birth: 'DD-MM-YYYY', life_expectancy, retirement_age }). Then individual fields are at \`assumptions.persons.0.<field>\`, \`assumptions.persons.1.<field>\`, etc.
- **assumptions.growth.{cash,investment,real_estate,vehicle}** (decimal fractions), **assumptions.taxes.{federal,state,capital_gains}**, **assumptions.inflation**
- **freedom_score_inputs**: age (integer years), monthly_income, monthly_expenses, monthly_emi, portfolio_current_value, liquid_assets_current_value, equity_allocation_percent, number_of_holdings, risk_tolerance — these are the inputs the freedom score and cashflow tools actually read. **Always also set the relevant freedom_score_inputs fields** when the user gives you their numbers.

## Path notation

Always use dot notation. NEVER use brackets. Correct: \`assumptions.persons.0.retirement_age\`. Wrong: \`assumptions.persons[0].retirement_age\`.

Lists you append to (\`financial_goals\`, \`assumptions.persons\`, \`mutual_funds\`, \`equity_stocks\`, \`fixed_income\`) use \`plan_add\` with the bare list path. The id is auto-generated.

A one-time future event (e.g. "annual family trip", "buy parent's house in 2031") goes in **financial_goals[]** via plan_add, NOT in monthly_expenses.
A recurring monthly expense change goes in **monthly_expenses.<key>** via plan_set.

## Rules

- **household_id**: Every tool call MUST include the household_id passed in the user message context. Never invent one.
- **Risk gate**: do not call allocate / tax / montecarlo tools until the household has \`computed.risk_profile.recommended_score\`. If a user asks for these and risk is unset, run the 3-question risk flow first.
- **Source priority**: user input > transcript > deterministic file > LLM-extracted file > inferred. Do not overwrite higher-priority data.
- **Null is sacred**: never fabricate SIP, EMI, salary, or insurance numbers. If unknown, leave it null and add to missing_fields.

You are concise. You are exact. You let the canvas speak through PlanState.`;

const tools = {
  intake_ingest: tool({
    description:
      'Universal intake dispatcher. Accepts a file (PDF, XLSX, CSV, DOCX, MD, TXT, image, audio) or pasted text/transcript and returns a partial PlanState delta with evidence and per-field confidence.',
    parameters: z.object({
      household_id: z.string(),
      source: z.union([
        z.object({
          kind: z.literal('file'),
          filename: z.string(),
          mime: z.string(),
          contents_b64: z.string(),
        }),
        z.object({
          kind: z.literal('text'),
          text: z.string(),
          source_type: z.enum(['user', 'transcript', 'md']).default('user'),
        }),
      ]),
    }),
    execute: async (args) => ingest(args),
  }),
  intake_confirm: tool({
    description:
      'Promote an LLM-extracted (low-confidence) field to confirmed when the user accepts it in chat.',
    parameters: z.object({
      household_id: z.string(),
      field: z.string(),
      value: z.unknown().optional(),
    }),
    execute: async (args) => confirmField(args),
  }),
  plan_set: tool({
    description: 'Set a single canonical field on PlanState (e.g. personal_details.date_of_birth).',
    parameters: z.object({
      household_id: z.string(),
      path: z.string(),
      value: z.unknown(),
      source_type: SOURCE_TYPE.default('user'),
    }),
    execute: async (args) => applySet(args),
  }),
  plan_add: tool({
    description:
      'Append a row to a list-typed canonical section (income, expenses, events, holdings, goals).',
    parameters: z.object({
      household_id: z.string(),
      path: z.string(),
      row: z.unknown(),
      source_type: SOURCE_TYPE.default('user'),
    }),
    execute: async (args) => applyAdd(args),
  }),
  plan_remove: tool({
    description: 'Remove a row by id from a list-typed canonical section.',
    parameters: z.object({
      household_id: z.string(),
      path: z.string(),
      id: z.string(),
    }),
    execute: async (args) => applyRemove(args),
  }),
  plan_assumption: tool({
    description:
      'Set an assumption value (per-person DOB / life expectancy / retirement age, growth rates, taxes, inflation).',
    parameters: z.object({
      household_id: z.string(),
      path: z.string(),
      value: z.unknown(),
    }),
    execute: async (args) => applyAssumption(args),
  }),
  risk_assess: tool({
    description:
      'Compute the 3-part risk profile (Capacity, Need, Willingness) and the reconciled recommended_score. Required before allocate / tax / montecarlo.',
    parameters: z.object({
      household_id: z.string(),
      willingness: z
        .object({
          volatility_reaction: z
            .enum(['sell_everything', 'sell_some', 'hold_steady', 'buy_more'])
            .optional(),
          risk_return_tradeoff: z.enum(['A', 'B', 'C', 'D']).optional(),
          max_tolerable_loss: z.enum(['0', '10', '20', '30', '>30']).optional(),
        })
        .optional(),
    }),
    execute: async (args) => riskAssess(args),
  }),
  allocate_recommend: tool({
    description:
      'Strategic + bounded tactical India allocation. Refuses if risk gate not passed.',
    parameters: z.object({ household_id: z.string() }),
    execute: async (args) => allocateRecommend(args),
  }),
  freedom_score: tool({
    description: 'Compute the 5-pillar Freedom Score (0-100) with city-sensitive insurance logic.',
    parameters: z.object({ household_id: z.string() }),
    execute: async (args) => freedomScoreFn(args),
  }),
  tax_harvest: tool({
    description:
      'Compute LTCG/STCG harvest suggestions, loss harvesting, combined impact, and fee-vs-value gates for the current FY. Refuses if risk gate not passed.',
    parameters: z.object({ household_id: z.string() }),
    execute: async (args) => taxHarvest(args),
  }),
  cashflow_project: tool({
    description: 'Year-by-year cash flow projection + 12-month forward strip + retirement glide.',
    parameters: z.object({
      household_id: z.string(),
      horizon_years: z.number().int().min(5).max(80).default(45),
    }),
    execute: async (args) => cashflowProject(args),
  }),
  scenario_pin: tool({
    description:
      'Pin the current plan as a scenario (Plan A or Plan B). Adds a second curve and a second headline line.',
    parameters: z.object({
      household_id: z.string(),
      label: z.string(),
      mutation: z
        .object({
          ops: z.array(
            z.object({
              path: z.string(),
              op: z.enum(['set', 'add', 'remove']),
              value: z.unknown().optional(),
              row: z.unknown().optional(),
              id: z.string().optional(),
            }),
          ),
        })
        .optional(),
    }),
    execute: async (args) => pin(args),
  }),
  scenario_diff: tool({
    description: 'Diff two scenarios and return per-field deltas + projection deltas.',
    parameters: z.object({
      household_id: z.string(),
      a: z.string(),
      b: z.string(),
    }),
    execute: async (args) => diff(args),
  }),
  montecarlo_run: tool({
    description:
      '2,000-path Monte Carlo. Outputs P10/P50/P90 freedom-age. Refuses if risk gate not passed.',
    parameters: z.object({
      household_id: z.string(),
      paths: z.number().int().min(500).max(10_000).default(2000),
    }),
    execute: async (args) => runMonteCarlo(args),
  }),
  knowledge_retrieve: tool({
    description:
      'Retrieve top-K chunks from the firm knowledge base. Returns chunk text + filename + heading + similarity score for inline citation.',
    parameters: z.object({
      org_id: z.string().default('main'),
      query: z.string(),
      top_k: z.number().int().min(1).max(10).default(3),
    }),
    execute: async (args) => knowledgeRetrieve(args),
  }),
  news_relevance: tool({
    description:
      'Score how relevant each news item is for a specific household, using sector × direct holdings × asset-class exposure.',
    parameters: z.object({
      household_id: z.string(),
      top_k: z.number().int().min(1).max(20).default(5),
    }),
    execute: async (args) => relevanceForHousehold(args),
  }),
};

export type ToolCallEvent = { id: string; name: string; args: unknown };
export type ToolResultEvent = { id: string; name: string; result: unknown };

export type RunPlannerArgs = {
  householdId: string;
  chatId?: string;
  message: string;
  onToolCall?: (ev: ToolCallEvent) => void | Promise<void>;
  onToolResult?: (ev: ToolResultEvent) => void | Promise<void>;
};

/**
 * Per-(household, chat) conversation memory. Multiple chats per household
 * supported — each chat has its own independent message history but they
 * all edit the same underlying PlanState.
 */
const convoMemory = new Map<string, CoreMessage[]>();
const MAX_HISTORY_MESSAGES = 60;

const memKey = (householdId: string, chatId = 'main') => `${householdId}::${chatId}`;

export function clearConvo(householdId: string, chatId?: string) {
  convoMemory.delete(memKey(householdId, chatId));
}

export function getConvo(householdId: string, chatId?: string): CoreMessage[] {
  return convoMemory.get(memKey(householdId, chatId)) ?? [];
}

/**
 * Restore server-side convo memory from a client-supplied transcript — used
 * when localStorage has chat history but the backend lost it (process
 * restart). Only plain user + assistant turns are mirrored; tool calls
 * aren't replayed since their results may no longer be valid.
 */
export function hydrateConvo(
  householdId: string,
  chatId: string | undefined,
  turns: { role: 'user' | 'assistant'; text: string }[],
) {
  const messages: CoreMessage[] = turns
    .filter((t) => t.text && t.text.trim())
    .slice(-MAX_HISTORY_MESSAGES)
    .map((t) =>
      t.role === 'user'
        ? { role: 'user', content: `[household_id=${householdId}]\n\n${t.text}` }
        : { role: 'assistant', content: t.text },
    );
  convoMemory.set(memKey(householdId, chatId), messages);
}

export async function runPlannerTurn({
  householdId,
  chatId,
  message,
  onToolCall,
  onToolResult,
}: RunPlannerArgs) {
  const userText =
    (message ?? '').trim() || '(empty user turn — read state and ask a clarifying question)';

  const key = memKey(householdId, chatId);
  const history = convoMemory.get(key) ?? [];
  const userMessage: CoreMessage = {
    role: 'user',
    content: `[household_id=${householdId}]\n\n${userText}`,
  };
  const messages: CoreMessage[] = [...history, userMessage];

  const modelId = process.env.PLANNER_MODEL ?? 'claude-sonnet-4-6';
  const result = await generateText({
    model: anthropic(modelId),
    system: SYSTEM_PROMPT,
    messages,
    tools,
    maxSteps: 8,
    temperature: 0.2,
    onStepFinish: async (step) => {
      if (onToolCall && step.toolCalls?.length) {
        for (const call of step.toolCalls) {
          await onToolCall({
            id: (call as { toolCallId?: string }).toolCallId ?? call.toolName,
            name: call.toolName,
            args: call.args,
          });
        }
      }
      if (onToolResult && step.toolResults?.length) {
        for (const tr of step.toolResults) {
          const t = tr as { toolCallId?: string; toolName: string; result: unknown };
          await onToolResult({
            id: t.toolCallId ?? t.toolName,
            name: t.toolName,
            result: t.result,
          });
        }
      }
    },
  });

  // Persist the user turn + every message the model produced (including the
  // assistant tool-use blocks and the tool-result blocks) so the next turn
  // sees the full context. Trim from the head once we exceed the cap.
  const fresh = (result.response?.messages ?? []) as CoreMessage[];
  const next = [...history, userMessage, ...fresh].slice(-MAX_HISTORY_MESSAGES);
  convoMemory.set(key, next);

  return { text: result.text ?? '', steps: result.steps ?? [] };
}
