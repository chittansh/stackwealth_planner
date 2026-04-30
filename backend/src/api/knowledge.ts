import { Hono } from 'hono';
import { ingestDocument, listDocuments, retrieve } from '../skills/knowledge/index.js';
// @ts-expect-error pdf-parse has no shipped types
import pdfParse from 'pdf-parse';
import * as XLSX from 'xlsx';
import mammoth from 'mammoth';

export const knowledgeRoute = new Hono();

knowledgeRoute.get('/:org', async (c) => {
  const org = c.req.param('org');
  return c.json({ docs: listDocuments(org) });
});

knowledgeRoute.post('/:org', async (c) => {
  const org = c.req.param('org');
  const form = await c.req.parseBody({ all: true });
  const file = form['file'] as File | File[] | undefined;
  const files = Array.isArray(file) ? file : file ? [file] : [];
  const results: { doc_id: string; chunk_count: number; filename: string }[] = [];
  for (const f of files) {
    const buf = Buffer.from(await f.arrayBuffer());
    const text = await extractText(f.name, buf);
    const r = await ingestDocument({ org_id: org, filename: f.name, text });
    results.push({ ...r, filename: f.name });
  }
  return c.json({ ok: true, results });
});

knowledgeRoute.post('/:org/retrieve', async (c) => {
  const org = c.req.param('org');
  const body = await c.req.json<{ query: string; top_k?: number }>();
  return c.json(await retrieve({ org_id: org, query: body.query, top_k: body.top_k ?? 3 }));
});

async function extractText(filename: string, buf: Buffer): Promise<string> {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.pdf')) {
    return ((await pdfParse(buf)).text ?? '') as string;
  }
  if (lower.match(/\.xlsx?$/)) {
    const wb = XLSX.read(buf, { type: 'buffer' });
    return wb.SheetNames.map((n) => `## ${n}\n${XLSX.utils.sheet_to_csv(wb.Sheets[n])}`).join('\n\n');
  }
  if (lower.endsWith('.docx')) {
    const out = await mammoth.convertToMarkdown({ buffer: buf });
    return out.value;
  }
  return buf.toString('utf8');
}
