/**
 * /api/chat — streams the planner's response. Surfaces tool calls + tool
 * results as live SSE events and runs every assistant text through the
 * numbers-from-tools validator before sending to the client.
 *
 * SSE event shape:
 *   status      — "thinking" once at the start
 *   tool_call   — { id, name, args }   (one per tool call)
 *   tool_result — { id, name, result } (one per tool result; same id as the call)
 *   message     — { role: 'assistant', text }  final assistant text
 *   done        — "ok"
 *   error       — { message }
 */
import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import { runPlannerTurn, clearConvo, hydrateConvo } from '../agent/planner.js';
import { collectNumbers, validateAssistantText } from '../agent/validator.js';
import { getPlan } from '../db/client.js';

export const chatRoute = new Hono();

chatRoute.post('/:id/reset', async (c) => {
  const chatId = c.req.query('chat_id') ?? undefined;
  clearConvo(c.req.param('id'), chatId);
  return c.json({ ok: true });
});

/**
 * Restore server-side convo memory from a client-supplied transcript so the
 * agent has context after a backend restart or chat-switch from localStorage.
 */
chatRoute.post('/:id/hydrate', async (c) => {
  const chatId = c.req.query('chat_id') ?? undefined;
  const body = await c.req
    .json<{ turns: { role: 'user' | 'assistant'; text: string }[] }>()
    .catch(() => ({ turns: [] as { role: 'user' | 'assistant'; text: string }[] }));
  hydrateConvo(c.req.param('id'), chatId, body.turns ?? []);
  return c.json({ ok: true, restored: (body.turns ?? []).length });
});

chatRoute.post('/', async (c) => {
  const body = await c.req.json<{
    household_id: string;
    chat_id?: string;
    message: string;
    attachments?: { kind: 'file' | 'text'; payload: unknown }[];
  }>();

  return streamSSE(c, async (stream) => {
    await stream.writeSSE({ event: 'status', data: 'thinking' });

    // Prime the validator's bag with every number already in PlanState — the
    // agent can reference these in prose even when no tool call fires this turn.
    const seenNumbers = new Set<string>();
    const priorPlan = await getPlan(body.household_id).catch(() => null);
    if (priorPlan) collectNumbers(priorPlan, seenNumbers);

    try {
      const result = await runPlannerTurn({
        householdId: body.household_id,
        chatId: body.chat_id,
        message: body.message ?? '',
        onToolCall: async (ev) => {
          collectNumbers(ev.args, seenNumbers);
          await stream.writeSSE({
            event: 'tool_call',
            data: JSON.stringify(ev),
          });
        },
        onToolResult: async (ev) => {
          collectNumbers(ev.result, seenNumbers);
          await stream.writeSSE({
            event: 'tool_result',
            data: JSON.stringify(ev),
          });
        },
      });

      const validated = validateAssistantText(result.text, seenNumbers);

      // Emit Langfuse trace pointers BEFORE the assistant message so the
      // frontend can stamp them onto the rendered bubble for feedback.
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
        data: JSON.stringify({ role: 'assistant', text: validated }),
      });
      await stream.writeSSE({ event: 'done', data: 'ok' });
    } catch (err) {
      console.error('[chat] error:', err);
      await stream.writeSSE({
        event: 'error',
        data: JSON.stringify({ message: (err as Error).message }),
      });
    }
  });
});
