---
name: repo-practices
description: Onboarding map for the stackwealth_planner monorepo — file layout, conventions, where state lives, where to add new tools / views / skills. Invoke when working in this codebase or when a new contributor is getting started.
---

# Stackwealth Planner — Repo Practices

This is a **pnpm workspace** with three packages: `backend`, `frontend`, `shared`. Read this before adding anything new — most "where do I put X?" questions are answered here.

---

## Top-level layout

```
stackwealth_planner/
├── backend/        # Hono server + agent + skills + Drizzle types
├── frontend/       # Next.js 15 (App Router) + Tailwind v4 + Recharts
├── shared/         # Single TS file: PlanState type (ts only, no build)
├── package.json    # workspace root, scripts proxied to children
├── pnpm-workspace.yaml
├── DEPLOY.md       # full Fly.io deploy guide
├── DEPLOY_NOW.md   # quick-deploy commands (rotate keys + delete after first deploy)
└── LIVE.md         # how to use the live deployment + smoke tests
```

The `shared` package isn't compiled — it's TS source that both apps import via relative paths (`../../../shared/types/plan-state.ts` from backend, `../../../shared/...` from frontend). NEVER `npm publish` shared; it's a workspace symlink.

---

## Backend (`backend/src/`)

```
src/
├── index.ts              # Hono boot + route mounts
├── agent/
│   ├── planner.ts        # The single orchestrator agent (Vercel AI SDK + Anthropic)
│   └── validator.ts      # Numbers-from-tools post-validator
├── api/                  # One Hono Hono route file per resource
│   ├── chat.ts           # SSE streaming chat (POST /api/chat, /:id/reset, /:id/hydrate)
│   ├── plan.ts           # GET/POST plan, /set, /add, /remove, /assumption
│   ├── upload.ts         # File upload → intake pipeline → applySet/applyAdd
│   ├── scenario.ts       # Pin / diff / toggle / clear scenarios
│   ├── skill.ts          # Direct REST entry for risk/freedom/allocate/tax/cashflow/MC
│   ├── advisor.ts        # /clients list + /highlights strip
│   ├── household.ts      # Merge preview + execute
│   ├── knowledge.ts      # KB upload + retrieve (RAG)
│   ├── news.ts           # News list + POST to add items
│   └── report.ts         # PDF render via Puppeteer (or HTML fallback)
├── skills/               # Pure compute — no HTTP, no LLM. Each is one folder.
│   ├── intake/           # Multi-model document extraction
│   │   ├── index.ts          # dispatcher (mime → parser)
│   │   ├── multimodalExtract.ts   # Claude → GPT-4o fallback (text/PDF/image)
│   │   ├── llmExtract.ts          # text-input wrapper for the multimodal extractor
│   │   ├── parsePdfAA.ts          # deterministic AA-PDF regex parser
│   │   ├── parsePdfGeneric.ts     # native-PDF via multimodal model
│   │   ├── parseImage.ts          # native vision; HEIC → JPEG via sharp
│   │   ├── parseXlsx.ts | parseCsv.ts | parseDocx.ts | parseAudio.ts | parseText.ts
│   ├── freedom/      # Freedom Score (5 pillars)
│   ├── cashflow/     # Year-by-year projection
│   ├── risk/         # 3-part risk profile (Capacity / Need / Willingness)
│   ├── allocate/     # India tactical allocator (uses signals/)
│   ├── tax/          # LTCG / STCG harvesting
│   ├── scenario/     # ★ THE plan-mutation engine + Plan A/B + Monte Carlo
│   ├── signals/      # Market regime snapshot (fixture-backed; cron later)
│   ├── news/         # Per-household news relevance scorer
│   ├── knowledge/    # Embedding + cosine retrieve over uploaded docs
│   ├── household/    # Multi-household merge logic
│   └── report/       # Puppeteer PDF
├── db/
│   ├── schema.ts     # Drizzle table defs (used only when DATABASE_URL is set)
│   └── client.ts     # Postgres OR in-memory store. Auto-detects placeholder URL.
├── seed/             # Currently a noop (was Jim & Pam etc., now stripped for RM mode)
└── types/plan-state.ts   # Re-exports from ../../../shared
```

### Key invariants

- **The agent never writes to PlanState directly.** Every mutation goes through `applySet / applyAdd / applyRemove / applyAssumption / confirmField` in `skills/scenario/index.ts`. Those functions enforce source priority + recompute.
- **`recompute()` is the single source of truth for derived data.** Called after every mutation. Updates `computed.{net_worth, freedom_score, cashflow, cash_flow_table, net_worth_series, headline_amount_at_horizon, milestone_pins}`. Never compute these elsewhere.
- **Dedup guard** (`findDuplicate` in `scenario/index.ts`): `plan_add` for `assumptions.persons` and `financial_goals` will REJECT a duplicate and return `{ ok: false, error: 'duplicate', existing_index, hint }`. The agent is taught to fall back to `plan_set`.
- **State snapshot is injected into the system prompt every turn** (`renderStateSummary` in `agent/planner.ts`). This is how the agent "knows" what already exists before adding.
- **Conversation memory is per (household_id, chat_id)** keyed in an in-process Map. Trimmed via `safeTrim` to never start with an orphaned `tool_result`.

### Where to add things

| You want to add… | Where it goes |
|---|---|
| A new agent tool | `backend/src/agent/planner.ts` — add a `tool({...})` entry in the `tools` object + describe it in the system prompt's "Tools you must use" section |
| A new skill (pure compute) | New folder under `backend/src/skills/<name>/index.ts` exporting a function that takes `{ household_id, ... }` |
| A new REST endpoint | New route file under `backend/src/api/<name>.ts`, mount in `backend/src/index.ts` |
| A new canonical PlanState field | `shared/types/plan-state.ts` — both apps pick it up |
| A new Drizzle column | `backend/src/db/schema.ts` then `pnpm --filter backend db:push` (only if DATABASE_URL is set) |

---

## Frontend (`frontend/src/`)

```
src/
├── app/
│   ├── page.tsx                    # / → redirects to /advisor/clients
│   ├── plan/[id]/
│   │   ├── page.tsx                # The 3-column workspace
│   │   └── report/page.tsx         # Print-styled report (Cormorant Garamond serif)
│   └── advisor/
│       ├── clients/page.tsx        # ClientsTable + HighlightsStrip
│       ├── household-merge/page.tsx
│       ├── knowledge/page.tsx
│       └── news/page.tsx
├── components/
│   ├── shell/                      # Frame chrome
│   │   ├── AppShell.tsx            # 3-column wrapper (icon rail · chat · canvas)
│   │   ├── AdvisorShell.tsx        # rail + sidebar + main (advisor pages)
│   │   ├── IconRail.tsx            # Left 52px nav rail with Settings popover
│   │   ├── TopBar.tsx              # Client name · view + horizon dropdowns · seg toggles · + · share · report
│   │   └── QuickAddMenu.tsx        # The `+` button popover → fires chat prompts
│   ├── chat/
│   │   ├── ChatPanel.tsx           # Main chat panel — drag/drop, multi-chat, hydration
│   │   ├── AskInput.tsx            # Auto-grow textarea + paste/drop + paperclip + mic
│   │   ├── MessageBubble.tsx       # User pill (lavender)
│   │   ├── AssistantMessage.tsx    # Markdown-rendered planner reply
│   │   ├── StatusPill.tsx          # In-flight (spinner) / done (matcha check) / error (zinc alert)
│   │   ├── ThinkingDots.tsx        # "thinking" indicator while waiting
│   │   ├── ToolGroup.tsx           # Collapsed "n tool calls" with running-state animation
│   │   ├── ToolCallCard.tsx        # Individual tool row inside a group
│   │   ├── ChatSwitcher.tsx        # Per-household chat picker (localStorage)
│   │   └── RiskGate.tsx            # 3-Q in-chat risk profile
│   ├── canvas/                     # Each canvas surface is its own component
│   │   ├── CanvasRouter.tsx        # Switches view based on URL ?view=
│   │   ├── Headline.tsx            # "In N years you'll have ₹X" + Freedom chip + NewsStrip
│   │   ├── NetWorthChart.tsx       # Recharts area + milestone pins
│   │   ├── CashFlowTable.tsx
│   │   ├── AllocationView.tsx
│   │   ├── TaxView.tsx
│   │   ├── GoalsView.tsx
│   │   ├── InsuranceView.tsx
│   │   ├── PlanBlocks.tsx          # 4-column container under the chart
│   │   ├── CurrentNetWorthCard.tsx | IncomeCard.tsx | ExpensesCard.tsx | OtherEventsCard.tsx
│   │   ├── AssumptionsCard.tsx
│   │   ├── Scenarios.tsx           # Sliders + Pin as Plan B + MC + Clear
│   │   ├── ScenarioChips.tsx       # Baseline / Scenario A / Scenario B legend
│   │   ├── MilestoneDrawer.tsx     # Click pin → side drawer
│   │   ├── RiskBanner.tsx
│   │   └── NewsStrip.tsx
│   ├── advisor/
│   │   ├── ClientsTable.tsx        # + New client form + table
│   │   ├── HighlightsStrip.tsx
│   │   ├── HouseholdMerge.tsx
│   │   ├── KnowledgeUpload.tsx
│   │   └── NewsBoard.tsx
│   ├── report/ReportView.tsx       # Print-styled cover + sections
│   └── ui/
│       ├── Dropdown.tsx            # Custom monochrome popover dropdown
│       └── Toast.tsx               # Bottom-center pill listening to sw:toast
├── lib/
│   ├── api.ts                      # All backend HTTP calls
│   ├── chatStore.ts                # localStorage chat persistence (multi-chat per household)
│   ├── prompt.ts                   # firePrompt() + firePlanChanged() event helpers
│   └── utils.ts                    # cn(), formatINR()
└── types/plan-state.ts             # Re-exports from ../../../shared
```

### Event bus (window CustomEvents)

Loose coupling between the chrome and the chat panel. **Always use these instead of prop drilling**:

| Event | Fired by | Listened by |
|---|---|---|
| `sw:chat-prompt` | TopBar segments, QuickAddMenu, plan card `+` buttons, AssumptionsCard, etc. | ChatPanel (sends as next user turn) |
| `sw:plan-changed` | TopBar (horizon change), MilestoneDrawer (save), Scenarios (pin/clear/MC), ChatPanel (after each tool result + after upload) | CanvasRouter (immediate refetch instead of waiting for poll) |
| `sw:toast` | TopBar (Share), IconRail (Settings actions) | `<Toast />` mounted in shells |

### Conventions

- **Always pass `householdId` down explicitly.** No global / context for it. URL is the source of truth.
- **Read PlanState via `fetchPlan(householdId)` + the polling loop in CanvasRouter.** Don't subscribe to backend state from chat-panel-only components.
- **Mutation pattern**: call `planSet`/`planAdd`/REST → call `firePlanChanged()` so the canvas refetches instantly.
- **Tailwind v4** — no config file, all tokens are in `globals.css` `:root`. Use `var(--color-accent)` (matcha) sparingly; everything else is grayscale (zinc shades).
- **No emojis in production code or copy** unless the user explicitly asked. The system prompt also bans them in agent replies.
- **Dropdowns** use `components/ui/Dropdown.tsx` — never `<select>` (browser chevron clashes with the design).
- **Status icons**: matcha for "done/good", zinc-500 for "warn/error", spinner for "in flight". No emerald/amber/rose.
- **Chat history** persists to localStorage via `chatStore.ts`. Server convo memory is hydrated from it on chat-switch.

---

## Live infra

- **Backend**: https://stackwealth-backend.fly.dev (Fly app `stackwealth-backend`, region `bom`)
- **Frontend**: https://stackwealth-frontend.fly.dev
- Backend runs `tsx src/index.ts` directly in production (no tsc build — sidesteps the rootDir/shared issue).
- Frontend uses Next.js standard `next start`. `NEXT_PUBLIC_BACKEND_URL` is **baked at build time** via `--build-arg`.
- No persistence: `DATABASE_URL` is unset → in-memory store on each Fly machine. RM-mode in production needs Neon Postgres.

See `DEPLOY.md` for full deploy guide and `LIVE.md` for live-deployment notes.

---

## Run / develop

```bash
# Install
pnpm install

# Two terminals
pnpm --filter backend dev      # tsx watch on :4000
pnpm --filter frontend dev     # next dev on :3000

# Tests (vitest fixtures for freedom, cashflow, risk, scenario, validator, news)
pnpm --filter backend test
```

`backend/.env` needs `ANTHROPIC_API_KEY` (required) + `OPENAI_API_KEY` (optional but enables vision fallback).
