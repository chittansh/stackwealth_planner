# Stackwealth Planner

AI-native financial planner for Indian households and advisors. Hiro-style three-column workspace: chat-led intake on the left, a live planning canvas on the right.

## Architecture

```
stackwealth_planner/
├── backend/      Hono API + Mastra agents + skills + Drizzle/Postgres
├── frontend/     Next.js 15 App Router + Tailwind + Recharts
└── shared/       Shared types (PlanState, schema)
```

The backend and frontend are separate apps. The frontend talks to the backend over HTTP.

## Stack

| Layer | Choice |
|---|---|
| Agent framework | [Mastra](https://mastra.ai) |
| LLM | Anthropic Claude Sonnet 4.6 (`@ai-sdk/anthropic`) |
| Backend server | Hono |
| Frontend | Next.js 15 (App Router) + React 19 |
| Styling | Tailwind v4 + shadcn-style components |
| Charts | Recharts |
| DB | Postgres (Neon) + Drizzle ORM |
| Vector store | `pgvector` |
| Embeddings | OpenAI `text-embedding-3-small` |
| PDF | `pdf-parse` + LLM fallback |
| Excel | SheetJS |
| Audio | OpenAI Whisper |

## Agents (Mastra)

A single orchestrator agent (`plannerAgent`) owns the conversation. It calls deterministic tools that mutate `PlanState`. Tools:

- `intake.ingest` — universal dispatcher (PDF, XLSX, CSV, DOCX, MD, TXT, image, audio → canonical JSON)
- `plan.set / plan.add / plan.remove` — direct state mutations
- `risk.assess` — 3-part Capacity / Need / Willingness profile
- `allocate.recommend` — strategic + tactical India allocation
- `freedom.score` — 5-pillar 0–100 score
- `tax.harvest` — gain/loss harvesting
- `cashflow.project` — 12-month + retirement glide
- `scenario.pin / scenario.diff` — Plan A/B compare
- `montecarlo.run` — 2,000-path simulation
- `knowledge.retrieve` — RAG over uploaded firm docs
- `news.relevance` — per-client market-news scoring

## Setup

```bash
# install
pnpm install

# env
cp backend/.env.example backend/.env       # add ANTHROPIC_API_KEY, DATABASE_URL, etc.
cp frontend/.env.example frontend/.env

# dev (two terminals)
pnpm --filter backend dev      # Hono on :4000
pnpm --filter frontend dev     # Next.js on :3000
```

## Design

See `../HIRO_STYLE_PLANNER_DESIGN.md` for the full UX and 7-day sprint plan.

## Status

Day-1 scaffold. The orchestrator agent + tool stubs are wired; deterministic skills and the canvas surfaces are filled in over Days 2–7.
