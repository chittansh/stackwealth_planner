/**
 * /api/chat — streams the plannerAgent's response. Surfaces tool calls as
 * status pills and runs every assistant text through the numbers-from-tools
 * validator before sending to the client.
 */
import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import { plannerAgent } from '../mastra/index.js';
import { collectNumbers, validateAssistantText } from '../agent/validator.js';

export const chatRoute = new Hono();

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
      const userText = body.message ?? '';
      const result = await plannerAgent.generate(
        [{ role: 'user', content: userText }],
        {
          context: { household_id: body.household_id },
          maxSteps: 8,
        },
      );

      for (const step of result.steps ?? []) {
        for (const call of step.toolCalls ?? []) {
          await stream.writeSSE({
            event: 'tool_call',
            data: JSON.stringify({ name: call.toolName, args: call.args }),
          });
        }
        for (const tr of step.toolResults ?? []) {
          collectNumbers(tr.result, seenNumbers);
        }
      }

      const validated = validateAssistantText(result.text ?? '', seenNumbers);

      await stream.writeSSE({
        event: 'message',
        data: JSON.stringify({ role: 'assistant', text: validated }),
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
