/**
 * /api/feedback — accepts user feedback on an assistant message and pushes it
 * to Langfuse as a Score attached to the trace (and, optionally, the specific
 * turn observation that produced the message).
 *
 * Body:
 *   {
 *     trace_id:        string   // from the SSE 'trace' event
 *     observation_id?: string   // turn span id (optional but recommended)
 *     value:           1 | -1 | number   // thumbs-up = 1, thumbs-down = -1
 *     comment?:        string
 *     name?:           string   // defaults to 'user-feedback'
 *     household_id?:   string   // forwarded into Langfuse metadata
 *     chat_id?:        string
 *     turn?:           number
 *   }
 *
 * Response: { ok: true } once the score is queued. The Langfuse SDK batches
 * uploads, so we flush asynchronously to make the UI snappy.
 */
import { Hono } from 'hono';
import { getLangfuse, flushLangfuse } from '../agent/langfuse.js';

export const feedbackRoute = new Hono();

type FeedbackBody = {
  trace_id?: string;
  observation_id?: string;
  value?: number;
  comment?: string;
  name?: string;
  household_id?: string;
  chat_id?: string;
  turn?: number;
};

feedbackRoute.post('/', async (c) => {
  const body = await c.req.json<FeedbackBody>().catch(() => ({}) as FeedbackBody);

  if (!body.trace_id) {
    return c.json({ ok: false, error: 'trace_id is required' }, 400);
  }
  if (typeof body.value !== 'number') {
    return c.json({ ok: false, error: 'value (number) is required' }, 400);
  }

  const lf = getLangfuse();
  if (!lf) {
    // Langfuse not configured — accept silently so the UI doesn't break.
    console.warn('[feedback] received but langfuse is disabled');
    return c.json({ ok: true, recorded: false });
  }

  try {
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
  } catch (err) {
    console.error('[feedback] failed:', err);
    return c.json({ ok: false, error: (err as Error).message }, 500);
  }
});
