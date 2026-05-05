---
name: add-tool
description: Scaffold a new agent tool end-to-end. Pass the tool name + a one-line description; this skill walks the user through wiring it in 4 places that MUST stay in sync (planner.ts tool def, planner.ts system prompt, REST endpoint, ToolCallCard humanizer). Each missing spot causes a silent bug.
---

# add-tool — scaffold a new agent tool

When you add a tool to the planner, **four files must stay in sync**. If any one is missed, the failure mode is silent or confusing:

| Forgot to update | Symptom |
|---|---|
| `agent/planner.ts` tool def | Tool doesn't exist; agent never calls it |
| `agent/planner.ts` system prompt "Tools you must use" + worked examples | Agent doesn't know when to call it |
| `api/<resource>.ts` REST endpoint | UI buttons that bypass chat (e.g. RiskGate, TaxView) can't trigger it |
| `frontend/.../chat/ToolCallCard.tsx` `FRIENDLY` map | The tool row in chat shows raw `snake_case_name` instead of a friendly label |

## Naming

Tool name **must** be `^[a-zA-Z0-9_-]{1,128}$` (Anthropic's rule). Use `snake_case`. Examples already in use:

```
intake_ingest, intake_confirm,
plan_set, plan_add, plan_remove, plan_assumption,
risk_assess, allocate_recommend, freedom_score, tax_harvest,
cashflow_project,
scenario_pin, scenario_diff, montecarlo_run,
knowledge_retrieve, news_relevance
```

A new one should follow the convention `<resource>_<verb>`.

## Procedure

### Inputs needed from the user

- `name` — `snake_case`, e.g. `tax_filing_check`
- `purpose` — one-sentence summary; goes in description AND system prompt
- `inputs` — what fields it takes (esp. whether it needs `household_id`)
- `output` — what shape it returns
- `gate` — does it need risk profile to be set first? (allocation / tax / MC do)
- `compute_path` — does an existing skill compute this, or do you need a new `skills/<name>/index.ts`?

### Step 1 — Add the tool definition (`backend/src/agent/planner.ts`)

In the `tools = { ... }` object:

```ts
new_tool_name: tool({
  description: '<one-line purpose>. <optional details about gating>.',
  parameters: z.object({
    household_id: z.string(),
    // ...other inputs as zod schemas
  }),
  execute: async (args) => {
    // Either call an existing skill function:
    //   return existingSkillFn(args);
    // Or inline if it's trivial.
  },
}),
```

Place it alphabetically near related tools (e.g. `tax_*` next to `tax_harvest`). Match the existing tool style.

### Step 2 — Update the system prompt (`backend/src/agent/planner.ts`)

In the `SYSTEM_PROMPT` template literal, find the **"## Tools you must use"** section and add a bullet:

```
- For <when to use this tool> → \`new_tool_name\`. <Mention any gating>.
```

If the new tool depends on the risk gate, mention it in **"## Rules"** too:

```
- **Risk gate**: do not call ... or \`new_tool_name\` until ...
```

If the tool involves a non-obvious workflow (e.g. asking the user something first), add a worked example to **"### Worked examples"**:

```
User: "<example trigger phrase>"
   → \`new_tool_name(...)\`
   → THEN reply
```

### Step 3 — Add a REST endpoint (`backend/src/api/<resource>.ts`)

Skills are also exposed via REST so the UI can trigger them without going through chat (e.g. the "Run Monte Carlo" button in `Scenarios.tsx` hits `/api/skill/montecarlo/:id` directly).

Add a route handler in the relevant `api/<resource>.ts` file. If the tool is in a brand-new resource family, create `api/<resource>.ts` AND mount it in `backend/src/index.ts`.

Pattern:

```ts
<resourceRoute>.post('/<verb>/:id', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<...>().catch(() => ({} as ...));
  const r = await skillFn({ household_id: id, ...body });
  // If it produces something cached on the plan, persist:
  const plan = await getPlan(id);
  if (plan && r && !('error' in r)) {
    plan.computed.<field> = r;
    plan.last_updated_at = new Date().toISOString();
    await savePlan(plan);
  }
  return c.json(r);
});
```

If the skill mutates PlanState (most do via `applySet/applyAdd`), `recompute()` runs automatically — don't double-write.

### Step 4 — Add the friendly label (`frontend/src/components/chat/ToolCallCard.tsx`)

In the `FRIENDLY` map at the top of the file:

```ts
const FRIENDLY: Record<string, string> = {
  // ...
  new_tool_name: 'doing the thing',  // lowercase, present-tense, ≤25 chars
};
```

This is what the user sees in the collapsed tool row when the agent calls your tool. If you skip this, the row shows the raw `snake_case` name (functional but ugly).

### Step 5 — (Optional) Add a vitest fixture

If the new skill has interesting math, add a test in `backend/tests/<name>.test.ts`. Pattern from `freedom.test.ts`, `cashflow.test.ts`, etc.:

```ts
import { describe, it, expect } from 'vitest';
import { skillFn } from '../src/skills/<name>/index.js';
import { emptyPlanState } from '../src/types/plan-state.js';

describe('<name>', () => {
  it('produces sensible output for an empty plan', () => {
    const plan = emptyPlanState('hh-test');
    const r = skillFn(plan, ...);
    expect(r.<field>).toBeGreaterThanOrEqual(0);
  });
});
```

### Step 6 — Smoke test

Reset the convo to clear cached system prompt context, then ask the agent to do the thing:

```bash
BASE=http://localhost:4000   # or live URL
curl -X POST "$BASE/api/chat/test_$$/reset" -o /dev/null
curl -N -X POST "$BASE/api/chat" -H 'content-type: application/json' \
  -d '{"household_id":"test_'$$'","message":"<phrasing that should trigger your new tool>"}'
```

Look for:
- `event: tool_call` with `"name":"new_tool_name"` in the args
- `event: tool_result` with non-error result
- `event: message` with the agent narrating sensibly

## Quick reference

```
□ Step 1 — tool def in planner.ts (tools object)
□ Step 2 — bullet in SYSTEM_PROMPT "Tools you must use"
□ Step 3 — REST endpoint in api/<resource>.ts (mount in index.ts if new file)
□ Step 4 — FRIENDLY map in ToolCallCard.tsx
□ Step 5 — vitest fixture (if non-trivial math)
□ Step 6 — smoke test via /api/chat
```

If a step doesn't apply (e.g. UI never invokes this tool directly → skip step 3), call that out explicitly in your hand-off summary so the next person reading doesn't think you forgot.
