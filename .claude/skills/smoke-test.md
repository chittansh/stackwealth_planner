---
name: smoke-test
description: Run end-to-end curl smoke tests against the backend (live or local). Verifies health, household creation, plan read, agent chat round-trip, file upload, scenario pin, and skill endpoints. Use after deploys or when something feels broken.
---

# smoke-test — Stackwealth Planner

Smoke-tests the full backend API. **Argument** controls target:
- `live` (default) — `https://stackwealth-backend-py.fly.dev`
- `local` — `http://localhost:4000`
- `<custom-url>` — anything else

## Procedure

Set the base URL once:

```bash
BASE=https://stackwealth-backend-py.fly.dev   # or http://localhost:4000
```

Then walk through these checks in order. **Stop and report at the first failure** — don't keep poking a broken backend.

### 1. Health

```bash
curl -sS -m 10 "$BASE/health"
# expect: {"ok":true,"ts":"..."}
```

If this fails: backend is down. `fly status --app stackwealth-backend-py` and `fly logs --app stackwealth-backend-py`.

### 2. Create a throwaway household

```bash
HID=$(curl -sS -X POST "$BASE/api/plan" \
  -H 'content-type: application/json' \
  -d '{"name":"Smoke Test '$(date +%s)'"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "household=$HID"
# expect: household=h_<8-hex-chars>
```

### 3. Read the empty plan

```bash
curl -sS "$BASE/api/plan/$HID" | python3 -c 'import sys,json;p=json.load(sys.stdin);print("name:",p["personal_details"].get("full_name"),"|computed.headline:",p["computed"]["headline_amount_at_horizon"])'
# expect: name: Smoke Test ... | computed.headline: 0
```

### 4. Direct mutation via REST

```bash
curl -sS -X POST "$BASE/api/plan/$HID/set" \
  -H 'content-type: application/json' \
  -d '{"path":"freedom_score_inputs.age","value":32}' | head
# expect: {"ok":true,"updated_path":"freedom_score_inputs.age"}
```

### 5. Agent chat round-trip

This is the most failure-prone check — exercises Anthropic, conversation memory, tool execution, validator.

```bash
curl -sS -N -X POST "$BASE/api/chat" \
  -H 'content-type: application/json' \
  -d '{"household_id":"'$HID'","message":"my monthly take-home is 1.5L. capture that."}' \
  --max-time 60 | grep -E '^(event:|data:)' | head -30
```

Expect SSE events in this order:
- `event: status` `data: thinking`
- `event: tool_call` `data: {"id":"...","name":"plan_set",...}` (one or more)
- `event: tool_result` `data: {"id":"...","name":"plan_set","result":{"ok":true,...}}` (matching call IDs)
- `event: message` `data: {"role":"assistant","text":"..."}`
- `event: done` `data: ok`

If `event: error` instead → check the message. Common ones:
- `Anthropic API key is missing` → `fly secrets set --app stackwealth-backend-py ANTHROPIC_API_KEY=...`
- `unexpected tool_use_id found in tool_result blocks` → trim regression in `safeTrim` (see `agent/planner.ts`); reset chat: `curl -X POST "$BASE/api/chat/$HID/reset"`
- `tools.0.custom.name: String should match pattern` → tool name has a dot; must be `snake_case`

### 6. Verify the agent's mutation persisted

```bash
curl -sS "$BASE/api/plan/$HID" | python3 -c 'import sys,json;p=json.load(sys.stdin);print("monthly_income:",p["freedom_score_inputs"].get("monthly_income"),"|salary:",p["income_details"].get("client_salary_in_hand"))'
# expect: monthly_income: 150000 | salary: 150000
```

### 7. Skill — Freedom Score

```bash
curl -sS -X POST "$BASE/api/skill/freedom/$HID" | python3 -c 'import sys,json;r=json.load(sys.stdin);print("final_score:",r["final_score"],"pillars:",list(r["pillars"].keys()))'
# expect: final_score: <number 0-100> pillars: ['liquidity', 'debt', 'investment', 'discipline', 'risk']
```

### 8. Skill — Risk profile (gates allocation/tax/MC)

```bash
curl -sS -X POST "$BASE/api/skill/risk/$HID" \
  -H 'content-type: application/json' \
  -d '{"willingness":{"volatility_reaction":"hold_steady","risk_return_tradeoff":"C","max_tolerable_loss":"20"}}' | python3 -c 'import sys,json;r=json.load(sys.stdin);print("recommended:",r["recommended_score"],r["recommended_profile"])'
# expect: recommended: <0-100> <profile>
```

### 9. Skill — Allocation (depends on risk being set)

```bash
curl -sS -X POST "$BASE/api/skill/allocate/$HID" | python3 -c 'import sys,json;r=json.load(sys.stdin);print("strategic equity:",r["strategic_allocation"]["equity"],"recommended equity:",r["recommended_allocation"]["equity"],"regime:",r["tactical_regime_label"])'
# expect: strategic equity: <pct> recommended equity: <pct> regime: <label>
```

### 10. Scenario pin

```bash
curl -sS -X POST "$BASE/api/scenario/$HID/pin" \
  -H 'content-type: application/json' \
  -d '{"label":"Smoke Plan B","mutation":{"ops":[{"path":"assumptions.persons","op":"add","row":{"name":"Smoke","retirement_age":65}}]}}' | python3 -c 'import sys,json;r=json.load(sys.stdin);print("scenario_id:",r.get("id"),"label:",r.get("label"))'
# expect: scenario_id: <uuid> label: Smoke Plan B
```

### 11. Reset chat memory

```bash
curl -sS -X POST "$BASE/api/chat/$HID/reset"
# expect: {"ok":true}
```

### 12. Cleanup (optional — leave for inspection if you want)

There's no DELETE for households today. If you want to clean up, manually flush via the in-memory store on backend restart, or just leave it (each smoke run creates a fresh `Smoke Test <epoch>`).

## Output format

Return a green/red checklist:

```
## Smoke test — <BASE>

✓ /health
✓ create household → h_xxxxxxxx
✓ read empty plan
✓ POST /plan/:id/set
✓ POST /api/chat — agent ran 2 tool calls, returned reply in 4.3s
✓ verify mutation persisted (income_details.client_salary_in_hand=150000)
✓ /api/skill/freedom → 67/100
✓ /api/skill/risk → 50 (Moderate)
✓ /api/skill/allocate → strategic E50% / recommended E55% (Mild Risk-On)
✓ scenario pin → c_xxxxxxxx
✓ chat reset

All clear.
```

If anything fails, swap that line for `✗ <step> — <one-line reason>` and stop.
