/**
 * Langfuse tracing for the planner agent.
 *
 * Tracing model:
 *  - One Langfuse **session** per (household_id, chat_id). All turns in the
 *    same chat share the same sessionId, so the whole conversation rolls up
 *    under a single session view in the Langfuse UI.
 *  - One **trace** per planner turn (one user message → one assistant reply).
 *  - Each trace carries the **full conversation transcript** (every prior
 *    user/assistant turn, plus the new user message) as its input — so any
 *    individual trace is self-contained and shows the entire chat context.
 *  - Tool calls + tool results become spans under the trace.
 *  - The final LLM call is recorded as a generation with model, prompt, and
 *    completion text.
 *
 * The client is a no-op if LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not
 * set, so local dev without keys still works.
 */
import { Langfuse } from 'langfuse';
import type { CoreMessage } from 'ai';

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
    _client = null;
    return null;
  }

  _client = new Langfuse({
    publicKey,
    secretKey,
    baseUrl,
    flushAt: 1,
  });
  console.log(`[langfuse] tracing enabled (host=${baseUrl})`);
  return _client;
}

export function sessionIdFor(householdId: string, chatId?: string): string {
  return `${householdId}::${chatId ?? 'main'}`;
}

/**
 * Render a CoreMessage[] into a plain JSON-friendly transcript so Langfuse's
 * UI can display the full conversation as the trace input.
 */
export function transcriptForTrace(messages: CoreMessage[]) {
  return messages.map((m) => {
    const content = m.content;
    if (typeof content === 'string') {
      return { role: m.role, content };
    }
    if (Array.isArray(content)) {
      const parts = content.map((b) => {
        const obj = b as unknown as Record<string, unknown>;
        const type = (obj.type as string) ?? 'unknown';
        if (type === 'text') return { type, text: obj.text };
        if (type === 'tool-call' || type === 'tool_use')
          return { type, name: obj.toolName ?? obj.name, args: obj.args ?? obj.input };
        if (type === 'tool-result' || type === 'tool_result')
          return { type, name: obj.toolName ?? obj.name, result: obj.result ?? obj.content };
        return { type, ...obj };
      });
      return { role: m.role, content: parts };
    }
    return { role: m.role, content };
  });
}

export async function flushLangfuse() {
  const lf = getLangfuse();
  if (!lf) return;
  try {
    await lf.flushAsync();
  } catch (err) {
    console.warn('[langfuse] flush failed:', (err as Error).message);
  }
}
