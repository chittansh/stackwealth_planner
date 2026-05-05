# Stackwealth Planner — Live

Both apps are deployed on Fly.io in `bom` (Mumbai).

| | URL |
|---|---|
| **Frontend** (RM workspace) | https://stackwealth-frontend.fly.dev |
| **Backend** (API) | https://stackwealth-backend.fly.dev |

---

## How to use it (RM walk-through)

The frontend is built for **relationship managers handling multiple clients**. Open the URL above — you land on `/advisor/clients`, which is empty until you create your first household.

### 1. Create a client

Click **+ New client** → type a name (e.g. `Sharma Family`) → Enter. You're routed to `/plan/<uuid>` — that client's blank workspace.

### 2. Onboard the client (two ways)

**A. Just chat.** Type in the left panel:

```
hi, lets set up the plan from scratch
```

The agent greets and asks 1–2 facts at a time. Answer naturally — it captures every value into the plan via tool calls. Watch the cards on the right fill in live as you go.

Example exchange:

> **You:** im 32, mumbai. take-home is 1.5L/mo. expenses around 60k (rent 30k, groceries 15k, utilities 5k, school fees 10k). I have 3L savings, 5L in MFs. home loan EMI 25k with 8L outstanding, 5 years left. term insurance 50L cover, 8k annual premium. retirement at 60. want to buy a house in 2032 for 80L.
>
> **Planner:** Captured all of that. Updated:
> - personal_details, income_details, monthly_expenses, freedom_score_inputs
> - liquid_capital, loans_liabilities.home_loan, insurance_details.term_plan
> - assumptions.persons[0] (You, DOB-inferred, retirement age 60)
> - 1 financial_goal (House Purchase, 2032, ₹80L)
>
> Next — what's your monthly SIP into mutual funds? And do you have a spouse/partner whose finances we should include?

**B. Drop a document.** Drag a PDF, image, or screenshot onto the chat panel. The intake pipeline runs Claude Sonnet 4.6 first, falls back to GPT-4o on weak result, returns structured fields. The agent narrates what was extracted and asks for what's missing.

Supported formats: PDF, XLSX, CSV, DOCX, MD, TXT, PNG/JPEG/WebP/GIF, audio (MP3/WAV/MP4/WEBM via Whisper). HEIC iPhone photos won't work in production right now — re-export as JPEG.

### 3. Run the analytics

Once the basics are in (age + monthly income + monthly expenses + at least one goal), the canvas comes alive:

- **Net Worth view** — projection chart out to your selected horizon, milestone pins per goal
- **Cash Flow view** — year-by-year table
- **Allocation view** — strategic vs recommended donuts (gated until you complete a 3-Q risk profile)
- **Goals view** — timeline with on-track / at-risk / unrealistic per goal
- **Insurance view** — life + medical cover adequacy bars
- **Tax view** — LTCG headroom + harvest suggestions (gated by risk)

Try clicking the **Activity icon** in the top bar (next to chart/table) to fire a Monte Carlo simulation.

### 4. Multi-chat per client

Each client supports multiple chat threads. Use the chat picker (with the chat title) at the top of the chat panel + the **+** to start a fresh thread. Threads are persisted in localStorage and replayed to the agent on switch.

### 5. Switch clients

Click `← Clients` in the top bar to go back to the list, or use the IconRail's home icon. Each client has its own:
- PlanState (income, expenses, goals, …)
- Multiple chat threads
- Computed snapshots (cashflow, freedom score, allocation, …)

---

## Smoke tests (curl)

Run from anywhere — no auth required.

### Backend health

```bash
curl https://stackwealth-backend.fly.dev/health
# → {"ok":true,"ts":"..."}
```

### Create a household via API

```bash
curl -X POST https://stackwealth-backend.fly.dev/api/plan \
  -H 'content-type: application/json' \
  -d '{"name":"Test Family"}'
# → {"ok":true,"id":"h_<uuid>","created":true}
```

### Read a household's plan

```bash
curl https://stackwealth-backend.fly.dev/api/plan/h_<uuid>
```

### List all households (advisor view)

```bash
curl https://stackwealth-backend.fly.dev/api/advisor/clients
```

### Talk to the agent (SSE stream)

```bash
curl -N -X POST https://stackwealth-backend.fly.dev/api/chat \
  -H 'content-type: application/json' \
  -d '{"household_id":"h_<uuid>","message":"hi, lets set up my plan from scratch"}'
```

You'll see SSE events stream back: `status` → one or more `tool_call` + `tool_result` pairs → final `message` with the assistant's reply → `done`.

### Reset a chat (wipe agent convo memory for that thread)

```bash
curl -X POST 'https://stackwealth-backend.fly.dev/api/chat/h_<uuid>/reset'
```

### Run a skill directly

```bash
# Compute Freedom Score
curl -X POST https://stackwealth-backend.fly.dev/api/skill/freedom/h_<uuid>

# Run risk profile (3-question)
curl -X POST https://stackwealth-backend.fly.dev/api/skill/risk/h_<uuid> \
  -H 'content-type: application/json' \
  -d '{"willingness":{"volatility_reaction":"hold_steady","risk_return_tradeoff":"C","max_tolerable_loss":"20"}}'

# Recommend allocation (requires risk profile first)
curl -X POST https://stackwealth-backend.fly.dev/api/skill/allocate/h_<uuid>

# Tax harvest review (requires risk profile)
curl -X POST https://stackwealth-backend.fly.dev/api/skill/tax/h_<uuid>

# Cash flow projection
curl -X POST https://stackwealth-backend.fly.dev/api/skill/cashflow/h_<uuid> \
  -H 'content-type: application/json' \
  -d '{"horizon_years":45}'

# Monte Carlo (requires risk profile)
curl -X POST https://stackwealth-backend.fly.dev/api/skill/montecarlo/h_<uuid>
```

### Upload a file via API

```bash
curl -X POST 'https://stackwealth-backend.fly.dev/api/upload/h_<uuid>' \
  -F 'file=@/path/to/statement.pdf'
# → { ok, summaries: [{ filename, parser_used, sections_set, fields_extracted, missing }] }
```

---

## Things worth trying in the UI

Once you have a client with some data:

| Try | Where |
|---|---|
| **Switch the horizon** between 10 / 20 / 30 / 45 / 60 years | top-bar dropdown — chart + headline rebuild on the server live |
| **Switch the view** | `Net Worth ▾` dropdown or chart/table icons — calmly swaps the canvas |
| **Run Monte Carlo** | Activity icon in the top bar |
| **Pin a Plan B** | Scenarios card → adjust SIP delta / retirement delta / equity shock sliders → **Pin as Plan B**. Watch a second curve in matcha appear on the chart + a second headline line |
| **Edit a milestone** | Click any pin on the Net Worth chart |
| **Quick-add via the +** | Top-bar `+` button → income / expense / goal / asset / insurance / household member — fires the right chat prompt |
| **Tool transparency** | Each agent turn shows a collapsed "n tool calls" pill — click to expand → click any individual call to see args + result JSON |
| **Multi-chat** | Header chat picker → **+** for new chat. Threads persist in localStorage |
| **Knowledge base** | `/advisor/knowledge` — upload firm policy docs; agent will cite them inline |
| **News** | `/advisor/news` — POST news items via API, see per-client relevance scores |
| **Household merge** | `/advisor/household-merge` — combine clients into a household plan |

---

## Troubleshooting

### "I sent a message and the agent doesn't reply"

Tail the backend logs:

```bash
fly logs --app stackwealth-backend
```

Common causes:
- Anthropic key invalid / out of quota → 401/429 in logs
- Tool call failed → check the `tool_call` events in the SSE stream
- Cold start (machine was sleeping) — first request takes ~5–8s

### "File extraction returned nothing"

The chat shows a status pill that tells you what happened: *"Extracted N fields"* or *"Could not extract — re-export as JPEG / PNG / PDF / CSV"*. iPhone HEIC photos aren't supported in production (`sharp` not installed in the alpine base image).

### "I created a client and it disappeared"

The deployment uses an **in-memory store** (no `DATABASE_URL`). Each Fly machine has its own state. With `min_machines_running = 1` and 2 machines actually running for HA, the same client may hit different machines and see different data. To fix:
- Set `DATABASE_URL` to a Neon Postgres URL: `fly secrets set --app stackwealth-backend DATABASE_URL='postgres://…'`
- Or scale to 1 machine: `fly scale count 1 --app stackwealth-backend`

### "CORS error in browser console"

The frontend's URL must match the backend's `FRONTEND_ORIGIN`:

```bash
fly secrets list --app stackwealth-backend
# verify FRONTEND_ORIGIN=https://stackwealth-frontend.fly.dev
fly secrets set --app stackwealth-backend FRONTEND_ORIGIN=https://stackwealth-frontend.fly.dev
```

### "Backend changes aren't showing up"

The frontend's `NEXT_PUBLIC_BACKEND_URL` is **baked into the client bundle at build time**. If the backend URL changes, you must rebuild the frontend with the new build arg — `fly secrets set` won't help.

```bash
fly deploy --config frontend/fly.toml --dockerfile frontend/Dockerfile --remote-only \
  --build-arg NEXT_PUBLIC_BACKEND_URL=https://NEW-BACKEND-URL.fly.dev \
  --build-arg BACKEND_URL=https://NEW-BACKEND-URL.fly.dev
```

---

## Useful Fly commands

```bash
# Logs
fly logs --app stackwealth-backend
fly logs --app stackwealth-frontend

# Status (machines, regions, image)
fly status --app stackwealth-backend
fly status --app stackwealth-frontend

# SSH into a machine
fly ssh console --app stackwealth-backend

# Restart machines
fly machine restart --app stackwealth-backend

# Scale
fly scale count 2 --app stackwealth-backend
fly scale show --app stackwealth-backend

# Manage secrets
fly secrets list --app stackwealth-backend
fly secrets set --app stackwealth-backend KEY=value
fly secrets unset --app stackwealth-backend KEY

# Pause / resume an app to save money
fly machine stop --app stackwealth-backend
fly machine start --app stackwealth-backend
```

---

## Re-deploy after code changes

```bash
# Backend
fly deploy --config backend/fly.toml --dockerfile backend/Dockerfile --remote-only

# Frontend (must re-bake the BACKEND_URL build args)
fly deploy --config frontend/fly.toml --dockerfile frontend/Dockerfile --remote-only \
  --build-arg NEXT_PUBLIC_BACKEND_URL=https://stackwealth-backend.fly.dev \
  --build-arg BACKEND_URL=https://stackwealth-backend.fly.dev
```

---

## Production hardening checklist (when you're ready to upgrade past demo mode)

- [ ] **Set `DATABASE_URL`** (Neon Postgres) — required for true multi-user; without it data lives in memory and is per-machine
- [ ] **Rotate API keys** — the keys you used were pasted into chat / `DEPLOY_NOW.md`. Roll them in the Anthropic + OpenAI dashboards and `fly secrets set` the new ones
- [ ] **Add auth** — every household URL is currently world-readable
- [ ] **Install Puppeteer + `@sparticuz/chromium`** in the runtime image so `/api/report/:id/pdf` returns real PDFs instead of HTML fallback
- [ ] **Switch base image to `node:20-bookworm-slim`** + install `sharp` for HEIC iPhone photo support
- [ ] **Hook up real market signals** — `backend/src/seed/signals.fixture.json` is currently a static snapshot; fetch live NSE / RBI / AMFI / NSDL data on a daily cron
- [ ] **Hook up news ingestion** — `/api/news` currently has an empty store; POST items from your news feed
- [ ] **Set up monitoring** — Fly has built-in metrics; consider also Sentry for client errors
- [ ] **Lower `min_machines_running` to 0** + raise auto-stop idle threshold if you want to save further
