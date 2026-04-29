/**
 * /api/chat — streams the plannerAgent's response to a single user turn.
 * Returns Server-Sent Events: status pills, tool calls, and assistant text.
 */
import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import { plannerAgent } from '../mastra/index.js';

export const chatRoute = new Hono();

chatRoute.post('/', async (c) => {
  const body = await c.req.json<{
    household_id: string;
    message: string;
    attachments?: { kind: 'file' | 'text'; payload: unknown }[];
  }>();

  return streamSSE(c, async (stream) => {
    await stream.writeSSE({ event: 'status', data: 'thinking' });

    try {
      const userText = body.message ?? '';
      const result = await plannerAgent.generate(
        [{ role: 'user', content: userText }],
        {
          context: { household_id: body.household_id },
          maxSteps: 8,
        },
      );

      // Surface tool calls as "status pills" the frontend can render.
      for (const step of result.steps ?? []) {
        for (const call of step.toolCalls ?? []) {
          await stream.writeSSE({
            event: 'tool_call',
            data: JSON.stringify({ name: call.toolName, args: call.args }),
          });
        }
      }

      await stream.writeSSE({
        event: 'message',
        data: JSON.stringify({ role: 'assistant', text: result.text }),
      });
      await stream.writeSSE({ event: 'done', data: 'ok' });
    } catch (err) {
      await stream.writeSSE({
        event: 'error',
        data: JSON.stringify({ message: (err as Error).message }),
      });
    }
  });
});
