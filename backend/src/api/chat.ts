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
import { runPlannerTurn, clearConvo } from '../agent/planner.js';
import { collectNumbers, validateAssistantText } from '../agent/validator.js';

export const chatRoute = new Hono();

chatRoute.post('/:id/reset', async (c) => {
  clearConvo(c.req.param('id'));
  return c.json({ ok: true });
});

chatRoute.post('/', async (c) => {
  const body = await c.req.json<{
    household_id: string;
    message: string;
    attachments?: { kind: 'file' | 'text'; payload: unknown }[];
  }>();

  return streamSSE(c, async (stream) => {
    await stream.writeSSE({ event: 'status', data: 'thinking' });

    const seenNumbers = new Set<string>();

    try {
      const result = await runPlannerTurn({
        householdId: body.household_id,
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
