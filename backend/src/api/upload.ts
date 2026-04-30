/**
 * /api/upload — accepts any file type, dispatches to the universal intake
 * pipeline, applies the resulting deltas to PlanState.
 */
import { Hono } from 'hono';
import { ingest } from '../skills/intake/index.js';
import { applySet, applyAdd, confirmField } from '../skills/scenario/index.js';

export const uploadRoute = new Hono();

uploadRoute.post('/:id', async (c) => {
  const id = c.req.param('id');
  const form = await c.req.parseBody({ all: true });
  const file = form['file'] as File | File[] | undefined;
  const files = Array.isArray(file) ? file : file ? [file] : [];

  const results: unknown[] = [];

  for (const f of files) {
    const buf = Buffer.from(await f.arrayBuffer());
    const result = await ingest({
      household_id: id,
      source: {
        kind: 'file',
        filename: f.name,
        mime: f.type || 'application/octet-stream',
        contents_b64: buf.toString('base64'),
      },
    });
    results.push(result);

    // Apply each top-level partial section as a single set; lists go through add().
    for (const [path, value] of Object.entries(result.partial_state ?? {})) {
      if (Array.isArray(value)) {
        for (const row of value) {
          await applyAdd({ household_id: id, path, row, source_type: parserToSource(result.parser_used) });
        }
      } else {
        await applySet({ household_id: id, path, value, source_type: parserToSource(result.parser_used) });
      }
    }
  }

  return c.json({ ok: true, results });
});

uploadRoute.post('/:id/text', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ text: string; source_type?: 'user' | 'transcript' | 'md' }>();
  const result = await ingest({
    household_id: id,
    source: { kind: 'text', text: body.text, source_type: body.source_type ?? 'user' },
  });
  for (const [path, value] of Object.entries(result.partial_state ?? {})) {
    if (Array.isArray(value)) {
      for (const row of value) {
        await applyAdd({ household_id: id, path, row, source_type: 'user' });
      }
    } else {
      await applySet({ household_id: id, path, value, source_type: 'user' });
    }
  }
  return c.json({ ok: true, result });
});

uploadRoute.post('/:id/confirm', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ field: string; value?: unknown }>();
  const r = await confirmField({ household_id: id, field: body.field, value: body.value });
  return c.json(r);
});

function parserToSource(p: string): 'pdf_aa' | 'pdf_generic' | 'xlsx' | 'csv' | 'docx' | 'md' | 'image' | 'audio' {
  if (p.startsWith('pdfAA')) return 'pdf_aa';
  if (p.startsWith('pdfGeneric')) return 'pdf_generic';
  if (p.startsWith('xlsx')) return 'xlsx';
  if (p.startsWith('csv')) return 'csv';
  if (p.startsWith('docx')) return 'docx';
  if (p.startsWith('image')) return 'image';
  if (p.startsWith('audio')) return 'audio';
  return 'md';
}
