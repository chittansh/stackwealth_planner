---
name: langfuse-feedback
description: Add user-feedback (thumbs up/down + optional comment) to a chat agent that already has Langfuse tracing wired up. Each feedback click is recorded as a Langfuse Score attached to the trace + the specific turn observation that produced the message. Drop-in pattern for Node/TypeScript backends (Hono / Express / Next route handlers) and React/Next.js frontends. Pairs with the `langfuse-tracing` skill — you need that one in place first.
---

# langfuse-feedback — thumbs up/down on assistant messages

This skill assumes you already have **one trace per conversation, with each turn as a span** (per the `langfuse-tracing` skill). To collect feedback you need three pieces glued together:

1. **Backend exposes the trace id + the turn observation id** to the frontend on every assistant message.
2. **Frontend stamps those ids onto the rendered assistant bubble** and sends them back when the user clicks 👍 / 👎.
3. **A `POST /api/feedback` endpoint** calls `langfuse.score()` with those ids.

## Data flow

```
─ user message ──► /api/chat (SSE stream) ──┐
                                            │
backend:  runs the turn under                │
          trace.span(name='turn N: ...')     │
          ────► turnSpan.id (observation_id) │
                                             ▼
SSE events emitted in order:
   event: status        → "thinking"
   event: tool_call     → { id, name, args }
   event: tool_result   → { id, name, result }
   event: trace         → { trace_id, observation_id, turn }     ← NEW
   event: message       → { role, text }
   event: done          → "ok"

frontend: stores { traceId, observationId } on the assistant bubble.
          User clicks 👍 → POST /api/feedback with those ids.

backend:  /api/feedback → langfuse.score({ traceId, observationId, value, comment })
          → appears as a Score on that observation in the Langfuse UI.
```

## Why score the **observation**, not just the trace

A trace covers the entire conversation. If the user gives a thumbs-down on turn 7, scoring only the trace tells you "something in this 50-turn chat was bad" — useless. Scoring the **turn observation** pins the feedback to the exact assistant message that produced it. You can then sort observations by score in the Langfuse UI and dig into the bad ones.

The `traceId` is still on the score (Langfuse attaches it automatically when you pass `observationId`), so trace-level analytics still work.

## Step 1 — Backend: return the ids from the turn function

Make your turn runner return the trace id and the turn span's `id`:

```ts
export async function runTurn({...}) {
  // ...existing tracing setup (see langfuse-tracing skill)...

  const trace = lf?.trace({ id: meta.traceId, ... });
  const turnSpan = trace?.span({ name: `turn ${turn}: ...`, ... });

  // ... do the work ...

  return {
    text: result.text,
    // NEW — expose the ids so the route handler can ship them to the client
    traceId: trace ? meta.traceId : undefined,
    observationId: turnSpan?.id,
    turnNumber: turn,
  };
}
```

Both `LangfuseTraceClient` and `LangfuseSpanClient` expose a stable `.id` property — that's the value Langfuse uses internally and accepts on `score()`.

## Step 2 — Backend: emit the ids in the SSE stream

Right before you emit the assistant `message` event, write a `trace` event with the ids:

```ts
const result = await runTurn({...});

if (result.traceId) {
  await stream.writeSSE({
    event: 'trace',
    data: JSON.stringify({
      trace_id: result.traceId,
      observation_id: result.observationId,
      turn: result.turnNumber,
    }),
  });
}

await stream.writeSSE({
  event: 'message',
  data: JSON.stringify({ role: 'assistant', text: result.text }),
});
```

Order matters: emit `trace` **before** `message` so the frontend has the ids in hand by the time it renders the bubble. (You can also send them inside `message` as one JSON blob — emitting separately just keeps `message`'s shape stable for clients that don't care about feedback.)

If you're not using SSE (e.g. plain JSON response), just include `trace_id` / `observation_id` / `turn` in the response body next to `text`.

## Step 3 — Backend: the feedback endpoint

```ts
// src/api/feedback.ts
import { Hono } from 'hono';
import { getLangfuse, flushLangfuse } from '../agent/langfuse.js';

export const feedbackRoute = new Hono();

feedbackRoute.post('/', async (c) => {
  const body = await c.req.json<{
    trace_id?: string;
    observation_id?: string;
    value?: number;             // 1 = thumbs up, -1 = thumbs down
    comment?: string;
    name?: string;              // defaults to 'user-feedback'
    turn?: number;
  }>().catch(() => ({}));

  if (!body.trace_id) return c.json({ ok: false, error: 'trace_id is required' }, 400);
  if (typeof body.value !== 'number') return c.json({ ok: false, error: 'value (number) is required' }, 400);

  const lf = getLangfuse();
  if (!lf) {
    // Tracing disabled (no keys) — accept silently so the UI doesn't break.
    return c.json({ ok: true, recorded: false });
  }

  lf.score({
    traceId: body.trace_id,
    observationId: body.observation_id,
    name: body.name ?? 'user-feedback',
    value: body.value,
    dataType: 'NUMERIC',
    comment: body.comment,
  });

  void flushLangfuse();
  return c.json({ ok: true, recorded: true });
});
```

Mount it on your app: `app.route('/api/feedback', feedbackRoute);`.

### Why `dataType: 'NUMERIC'` with values 1 / -1

- **NUMERIC** lets you compute averages and trend lines in the Langfuse dashboard. A score of `0.7` over 100 turns means 70% positive, 15% negative, 15% (no feedback).
- **1 / -1** is more useful than **1 / 0** because absent feedback also reads as 0 — so `1 / -1` keeps "user disagreed" distinct from "user didn't bother".
- For star ratings, send the raw integer (1–5) and use the same name (`user-rating`).
- For free-form categories ("hallucinated", "rude", "outdated"), use `dataType: 'CATEGORICAL'` with `value: 'hallucinated'` and configure the category list in the Langfuse project settings.

You can attach **multiple scores with different names** to the same observation (e.g. one for thumbs, one for "did this hallucinate?"). Just call `score()` once per dimension.

## Step 4 — Frontend: capture the ids on the assistant message

If you stream the chat as SSE, add a handler for the `trace` event that stashes the ids in a closure variable, then attaches them to the next `message`:

```ts
let pendingTrace: { traceId?: string; observationId?: string; turn?: number } = {};

for await (const ev of streamChat(...)) {
  if (ev.event === 'trace') {
    const d = ev.data;
    pendingTrace = { traceId: d.trace_id, observationId: d.observation_id, turn: d.turn };
  } else if (ev.event === 'message') {
    const stamp = pendingTrace;
    pendingTrace = {};
    setMessages((m) => [...m, {
      kind: 'assistant',
      text: ev.data.text,
      traceId: stamp.traceId,
      observationId: stamp.observationId,
      turn: stamp.turn,
    }]);
  }
}
```

Persist `traceId` / `observationId` alongside the assistant text in your local message store (localStorage / Zustand / Redux) so the feedback buttons survive a reload.

## Step 5 — Frontend: the feedback buttons

```tsx
'use client';
import { useState } from 'react';
import { ThumbsUp, ThumbsDown, Check, X } from 'lucide-react';

async function submitFeedback(body: {
  trace_id: string;
  observation_id?: string;
  value: number;
  comment?: string;
  turn?: number;
}) {
  const r = await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

export function FeedbackRow({
  traceId,
  observationId,
  turn,
  feedback,                       // 1 | -1 | undefined — the value already submitted
  onSubmit,
}: {
  traceId: string;
  observationId?: string;
  turn?: number;
  feedback?: 1 | -1;
  onSubmit?: (value: 1 | -1, comment?: string) => void;
}) {
  const [showCommentBox, setShowCommentBox] = useState(false);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState<null | 1 | -1>(null);

  const send = async (value: 1 | -1, withComment?: string) => {
    setBusy(value);
    const r = await submitFeedback({
      trace_id: traceId,
      observation_id: observationId,
      value,
      comment: withComment,
      turn,
    });
    setBusy(null);
    if (r.ok) onSubmit?.(value, withComment);
  };

  if (feedback !== undefined) {
    return <div className="text-xs text-zinc-500">Feedback recorded</div>;
  }

  return (
    <div className="flex items-center gap-1">
      <button onClick={() => void send(1)} disabled={busy !== null}>
        <ThumbsUp size={12} />
      </button>
      <button onClick={() => setShowCommentBox(true)} disabled={busy !== null}>
        <ThumbsDown size={12} />
      </button>

      {showCommentBox && (
        <input
          autoFocus
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              void send(-1, comment.trim() || undefined);
              setShowCommentBox(false);
            }
          }}
          placeholder="What was off?"
        />
      )}
    </div>
  );
}
```

Drop `<FeedbackRow ... />` under each assistant bubble. Hide it (return `null`) when `traceId` is undefined — that means tracing is disabled (no Langfuse keys) or the message is local-only (e.g. a synthetic "Network error" reply).

### Optimistic UI

The submit button should:
- Disable both buttons while the request is in flight (don't let the user double-click)
- Call `onSubmit?.(value, comment)` on success so the parent can persist the choice in its message store and re-render in the "submitted" state
- On failure, show a small inline error and re-enable the buttons (don't auto-retry — feedback is a user-driven action)

## Step 6 — Verify

1. Send a chat message.
2. In the browser devtools Network tab, find the `/api/chat` SSE response and confirm there's an `event: trace` line carrying both ids.
3. Click 👍. The Network tab should show a `POST /api/feedback` returning `{"ok":true,"recorded":true}`.
4. In the **Langfuse UI** → open the trace → click the turn span → the **Scores** panel on the right shows `user-feedback: 1`.
5. Reload the page — the message should show "Feedback recorded" instead of fresh thumbs (proves persistence).

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| Thumbs buttons disabled / nothing visible | `traceId` is undefined on the message | Confirm the SSE `trace` event is firing; confirm the lazy `getLangfuse()` returned a client (keys present); confirm you're stamping the ids onto the message in the SSE handler |
| 400 from `/api/feedback` with "trace_id is required" | Frontend forgot to include the id, or the backend response didn't have it | Check the message in your store has `traceId`; check the `trace` SSE event arrived before `message` |
| Score appears on the trace but not on the turn observation | You omitted `observation_id` in the POST body | Always include `observation_id` if you have it — feedback is most actionable per-turn |
| Score never appears in Langfuse despite 200 OK | Process exits before the SDK flushes (serverless / short-lived handlers) | `await flushLangfuse()` before returning, or set `flushAt: 1` in the SDK constructor |
| User submits feedback twice | Buttons not disabled while request is in flight, or you re-render and lose state | Disable while `busy`; persist the chosen value to localStorage so it survives reload |
| Wrong assistant message gets credited | Race: a second message arrives before you stamped the previous `trace` event | Stamp synchronously in the same SSE iteration where `message` arrives; clear `pendingTrace` after each use |
| Feedback works locally but breaks in prod | Frontend is hitting localhost backend due to missing `NEXT_PUBLIC_BACKEND_URL` | Pass `--build-arg NEXT_PUBLIC_BACKEND_URL=...` (it's baked at build time, not runtime) |

## Beyond thumbs

The same `score()` API supports anything the Langfuse data model accepts. Once the trace / observation ids are wired through:

- **Star ratings** (1–5): same endpoint, send `value: 4`, `name: 'user-rating'`.
- **Categorical buckets** ("hallucinated", "rude", "outdated"): `dataType: 'CATEGORICAL'`, `value: 'hallucinated'`. Configure the categories in your Langfuse project.
- **Boolean flags** ("flagged for review"): `dataType: 'BOOLEAN'`, `value: 1` / `0`.
- **Auto-evals** (an LLM judges its own output): call `score()` from your backend after the generation completes. Same observation, different `name`.
- **Comment-only feedback**: send `value: 0` with a `comment` — Langfuse stores it; your dashboards can ignore the value field.

A single observation can carry multiple scores. Use distinct `name` fields to keep them queryable.

## Choosing what to score

- **One score per user-visible action**, not one per dimension. If you put a single 👍 / 👎 in your UI, send one score. Don't fan out to "helpfulness", "correctness", "tone" from one click — that's invented data.
- **Don't score the trace AND the observation with the same name**. Pick one. Observation gives you per-turn analytics; trace gives you per-conversation. The Langfuse UI rolls observation scores up to the trace automatically.
- **Don't auto-score on every turn.** Implicit signals (user copied the answer, user kept chatting, user closed the tab) belong in your own analytics, not in Langfuse Scores. Reserve Scores for explicit user signals + LLM-as-judge runs.

## When NOT to use this pattern

- **Anonymous public demos**: drive-by users will spam the buttons. Either rate-limit by IP, drop the buttons until login, or accept that the data is noisy.
- **Compliance environments where feedback contains PII**: a 👎 with the user typing "this is wrong, my SSN is X" lands in Langfuse plain-text. Either disable the comment box, or strip PII server-side before calling `score()`.
