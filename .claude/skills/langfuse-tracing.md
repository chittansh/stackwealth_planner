---
name: langfuse-tracing
description: Wire Langfuse tracing into a chat agent so the ENTIRE conversation lives in ONE trace (not one trace per turn). Each turn becomes a span under the same trace; tool calls and LLM calls nest under the turn span. Drop-in pattern for Node/TypeScript projects using the Vercel AI SDK, the Anthropic SDK, or the OpenAI SDK.
---

# langfuse-tracing — one trace per conversation

The default Langfuse pattern is **one trace per turn, grouped by `sessionId`**. That gives you a "Sessions" tab where you can see all turns of a chat, but each turn is still a separate top-level trace. If you want to open a single trace and see the entire conversation tree (every turn, every tool call, every LLM call) in one place, follow this skill.

## Tracing model

```
trace: chat <user_id>::<conversation_id>           ← persists for the whole chat
├── span: turn 1: <first user message>
│   ├── generation: agent.generateText             ← model + tokens
│   ├── span: tool.<name>                          ← each tool call
│   └── span: tool.<name>
├── span: turn 2: <second user message>
│   ├── generation: agent.generateText
│   └── span: tool.<name>
├── span: turn 3: ...
└── ...
```

- **One persistent trace per `(user_id, conversation_id)`**. The trace ID is generated once on the first turn and reused for every subsequent turn. Calling `langfuse.trace({ id: existingId, ... })` is an **upsert** — that's how you keep the same trace alive across turns.
- **Each turn is a span** under that trace. Use the user's message (truncated) as the span name so the tree is scannable.
- **Tool calls and the LLM generation are children of the turn span**, not children of the trace directly. That way a turn collapses to a self-contained block.
- The **trace's `output`** is rewritten on every turn with the latest cumulative transcript so opening the trace shows the entire conversation up to "now".

## Step 1 — install + env

```bash
pnpm add langfuse        # or npm / yarn / bun
```

```bash
# .env
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com   # or https://cloud.langfuse.com (EU)
```

For prod (Fly / Railway / Render / etc.), set the same three as secrets on the platform.

## Step 2 — Langfuse client module

Create `src/<agent>/langfuse.ts`. Lazy-initialize so the SDK is a no-op when keys are missing (local dev, CI without secrets).

```ts
import { Langfuse } from 'langfuse';

let _client: Langfuse | null = null;
let _initialized = false;

export function getLangfuse(): Langfuse | null {
  if (_initialized) return _client;
  _initialized = true;

  const publicKey = process.env.LANGFUSE_PUBLIC_KEY;
  const secretKey = process.env.LANGFUSE_SECRET_KEY;
  const baseUrl = process.env.LANGFUSE_BASE_URL ?? 'https://us.cloud.langfuse.com';

  if (!publicKey || !secretKey) {
    console.warn('[langfuse] keys not set — tracing disabled');
    return (_client = null);
  }

  _client = new Langfuse({ publicKey, secretKey, baseUrl, flushAt: 1 });
  console.log(`[langfuse] tracing enabled (host=${baseUrl})`);
  return _client;
}

export async function flushLangfuse() {
  const lf = getLangfuse();
  if (!lf) return;
  try { await lf.flushAsync(); } catch (err) {
    console.warn('[langfuse] flush failed:', (err as Error).message);
  }
}

/**
 * Render the agent's message array into a JSON-friendly transcript so
 * Langfuse can display the full conversation as the trace input/output.
 * Adapt the part-extraction to your message shape.
 */
export function transcriptForTrace(messages: any[]) {
  return messages.map((m) => {
    const c = m.content;
    if (typeof c === 'string') return { role: m.role, content: c };
    if (Array.isArray(c)) {
      return {
        role: m.role,
        content: c.map((b: any) => {
          if (b.type === 'text') return { type: 'text', text: b.text };
          if (b.type === 'tool-call' || b.type === 'tool_use')
            return { type: 'tool-call', name: b.toolName ?? b.name, args: b.args ?? b.input };
          if (b.type === 'tool-result' || b.type === 'tool_result')
            return { type: 'tool-result', name: b.toolName ?? b.name, result: b.result ?? b.content };
          return { type: b.type ?? 'unknown', ...b };
        }),
      };
    }
    return { role: m.role, content: c };
  });
}
```

## Step 3 — registry of trace IDs

Keep a `Map` keyed by the conversation key. The first turn allocates a UUID; every subsequent turn looks it up.

```ts
import { randomUUID } from 'node:crypto';

type TraceMeta = { traceId: string; turnNumber: number };
const traceRegistry = new Map<string, TraceMeta>();

const memKey = (userId: string, convoId = 'main') => `${userId}::${convoId}`;
```

Add a helper that resets the trace pointer when the user resets the chat — the next turn should start a fresh trace:

```ts
export function clearConvo(userId: string, convoId?: string) {
  const k = memKey(userId, convoId);
  // ...drop your conversation memory here...
  traceRegistry.delete(k);   // next turn opens a new trace
}
```

If you let clients hydrate transcripts from `localStorage` after a backend restart, also `traceRegistry.delete(k)` in the hydrate function — the original trace ID is gone and a fresh trace is the right behavior.

## Step 4 — instrument the turn function

This is the core pattern. Replace `runTurn` with whatever your agent's per-turn entry point is named.

```ts
export async function runTurn({ userId, convoId, message, history }: {
  userId: string;
  convoId?: string;
  message: string;
  history: CoreMessage[];   // your in-memory conversation
}) {
  const key = memKey(userId, convoId);
  const userMessage = { role: 'user' as const, content: message };
  const messages = [...history, userMessage];

  // ── 1. trace lookup / upsert ──────────────────────────────────────────
  const lf = getLangfuse();
  let meta = traceRegistry.get(key);
  const isFirstTurn = !meta;
  if (!meta) {
    meta = { traceId: randomUUID(), turnNumber: 0 };
    traceRegistry.set(key, meta);
  }
  meta.turnNumber += 1;
  const turn = meta.turnNumber;

  const trace = lf?.trace({
    id: meta.traceId,
    // Embed identifiers in the name so it's findable via the Langfuse
    // IDs/Names search box (which only matches trace id + name).
    name: `chat ${userId}::${convoId ?? 'main'}`,
    sessionId: `${userId}::${convoId ?? 'main'}`,
    userId,
    ...(isFirstTurn ? { input: { opening_user_message: message } } : {}),
    metadata: { user_id: userId, convo_id: convoId ?? 'main', latest_turn: turn },
    tags: ['agent', 'chat'],
  });

  // ── 2. one span per turn ──────────────────────────────────────────────
  const turnSpan = trace?.span({
    name: `turn ${turn}: ${message.slice(0, 60)}`,
    input: {
      user_message: message,
      prior_history: transcriptForTrace(history),
    },
    metadata: { turn, history_length: history.length },
  });

  // ── 3. generation under the turn span ─────────────────────────────────
  const generation = turnSpan?.generation({
    name: 'agent.generateText',
    model: 'claude-sonnet-4-6',                    // or whatever you call
    modelParameters: { temperature: 0.2 },
    input: { messages: transcriptForTrace(messages) },
  });

  // ── 4. tool spans under the turn span ─────────────────────────────────
  const toolSpans = new Map<string, ReturnType<NonNullable<typeof turnSpan>['span']>>();

  try {
    const result = await yourAgentCall({
      messages,
      onToolCall: ({ id, name, args }) => {
        if (turnSpan) {
          const s = turnSpan.span({
            name: `tool.${name}`,
            input: args,
            metadata: { tool_call_id: id, turn },
          });
          toolSpans.set(id, s);
        }
      },
      onToolResult: ({ id, result }) => {
        const s = toolSpans.get(id);
        if (s) { s.end({ output: result }); toolSpans.delete(id); }
      },
    });

    // ── 5. close generation + turn span, refresh trace output ───────────
    generation?.end({
      output: result.text,
      usage: result.usage && {
        input: result.usage.promptTokens,
        output: result.usage.completionTokens,
        total: result.usage.totalTokens,
      },
    });

    turnSpan?.end({ output: { assistant_text: result.text } });

    const merged = [...messages, { role: 'assistant', content: result.text }];
    trace?.update({
      output: {
        assistant_text_latest: result.text,
        turns: turn,
        full_conversation: transcriptForTrace(merged),
      },
    });

    void flushLangfuse();   // batched — don't await on the hot path
    return result;

  } catch (err) {
    for (const s of toolSpans.values()) {
      s.end({ level: 'ERROR', statusMessage: (err as Error).message });
    }
    generation?.end({ level: 'ERROR', statusMessage: (err as Error).message });
    turnSpan?.end({
      level: 'ERROR',
      statusMessage: (err as Error).message,
      output: { error: (err as Error).message },
    });
    trace?.update({ output: { last_error: (err as Error).message, turns: turn } });
    void flushLangfuse();
    throw err;
  }
}
```

### Vercel AI SDK adapter (`generateText`)

If your agent uses `ai.generateText`, the `onToolCall` / `onToolResult` callbacks above don't exist — wire them through `onStepFinish` instead:

```ts
const result = await generateText({
  model, system, messages, tools, maxSteps: 8, temperature: 0.2,
  onStepFinish: async (step) => {
    for (const call of step.toolCalls ?? []) {
      const id = call.toolCallId ?? call.toolName;
      if (turnSpan) {
        const s = turnSpan.span({ name: `tool.${call.toolName}`, input: call.args,
                                   metadata: { tool_call_id: id, turn } });
        toolSpans.set(id, s);
      }
    }
    for (const tr of step.toolResults ?? []) {
      const id = tr.toolCallId ?? tr.toolName;
      const s = toolSpans.get(id);
      if (s) { s.end({ output: tr.result }); toolSpans.delete(id); }
    }
  },
});
```

### Anthropic SDK adapter (raw `messages.create` loop)

If you're driving the tool loop yourself, open a tool span the moment you parse a `tool_use` block out of the model response, and close it the moment you push the matching `tool_result` block back into messages.

### OpenAI SDK adapter (`chat.completions` with tool calls)

Same idea — open the span when you see a `tool_calls` entry on the assistant message, close it when you append the `role: 'tool'` reply.

## Step 5 — verify

1. Run a multi-turn conversation against your endpoint.
2. Open the Langfuse UI → **Tracing** → search the IDs/Names box for `<your-user-id>` (this is why we baked it into the trace **name**).
3. You should see **exactly one trace**. Click it. The timeline tree shows every turn as a top-level span, with tool spans + the generation nested under each turn.
4. The trace's **Output** panel should contain `full_conversation` with every user/assistant message.

If you see one trace per turn instead of one trace per chat, the upsert isn't working — confirm:
- You're passing the SAME `traceId` to `langfuse.trace({ id })` on every turn.
- The `traceRegistry` map persists across requests (i.e. it's a module-level singleton, not allocated inside the request handler).

If search by `<user_id>` returns nothing, check that the trace **name** embeds the user_id. The IDs/Names search field matches trace id + trace name, NOT userId. (Use the Users tab to filter by userId, or the Sessions tab for sessionId.)

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| Each turn is its own trace | `traceId` not persisted across turns, or you're calling `lf.trace({})` without the `id` field | Pass `id: meta.traceId` every time |
| Trace shows only the latest turn's spans | You're calling `trace.update({ output })` overwriting on every turn — that's fine, but if you also drop the registry between turns the spans become orphans | Keep `traceRegistry` as a module-level `Map` |
| Search by user_id returns nothing | IDs/Names box only matches trace id + name | Embed the user_id in the trace **name** (`chat <user>::<convo>`) |
| Tool spans appear at the trace root, not under the turn | You called `trace.span(...)` instead of `turnSpan.span(...)` | Always nest tool spans under the turn span |
| Traces never appear despite no errors | Process exits before the SDK flushes | `await flushLangfuse()` before `process.exit` (serverless), or set `flushAt: 1` |
| Local dev crashes when keys are missing | SDK constructor was called without keys | Use the lazy `getLangfuse()` pattern — it returns null when keys absent |
| Traces stop ingesting in prod | Langfuse billing issue (banner in UI) | Update payment in Langfuse → Org Settings → Billing |

## Choosing user_id and convo_id

- **`user_id`**: stable identity per end-user. For a multi-tenant app, this is your tenant or end-user ID. For a B2B app where one user can have multiple chats, it's the user id (not the chat id).
- **`convo_id`**: stable identity per conversation/thread. If a "new chat" button creates a fresh thread, that thread gets a new `convo_id`. Old chats keep their old id (and their old trace).

The `(user_id, convo_id)` pair is what determines whether a turn extends an existing trace or opens a new one.

## When NOT to use this pattern

- **Long-lived conversations (>1000 turns)**: a single trace with thousands of spans gets slow to render in the Langfuse UI. Roll over to a fresh trace every N turns and link them via metadata.
- **High-concurrency single-conversation systems** (e.g. a shared support inbox): the in-memory `traceRegistry` is per-process. Behind a load balancer, two replicas will allocate two separate traces for the same chat. Either pin the chat to one replica (sticky session), or move the registry to Redis.
