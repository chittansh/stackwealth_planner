/**
 * Knowledge RAG — chunk + embed + cosine retrieve.
 *
 * Uses OpenAI text-embedding-3-small. Falls back to keyword + filename
 * match when OPENAI_API_KEY is missing. Storage: in-memory by default,
 * pgvector once Day 5 wires the production DB path.
 */
import OpenAI from 'openai';
import { randomUUID } from 'node:crypto';

let _client: OpenAI | null = null;
function client() {
  if (!process.env.OPENAI_API_KEY) return null;
  if (!_client) _client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  return _client;
}

type Chunk = {
  id: string;
  doc_id: string;
  org_id: string;
  filename: string;
  heading?: string;
  text: string;
  embedding: number[] | null;
  ord: number;
};

type Doc = { id: string; org_id: string; filename: string; uploaded_at: string };

const DOCS: Doc[] = [];
const CHUNKS: Chunk[] = [];

const CHUNK_SIZE = 1200; // chars; ≈ 300 tokens
const CHUNK_OVERLAP = 150;

function chunkText(s: string): { heading?: string; text: string }[] {
  const lines = s.split('\n');
  const out: { heading?: string; text: string }[] = [];
  let buf = '';
  let heading: string | undefined;
  const flush = () => {
    if (buf.trim()) out.push({ heading, text: buf.trim() });
    buf = '';
  };
  for (const line of lines) {
    if (/^#{1,6}\s/.test(line)) {
      flush();
      heading = line.replace(/^#{1,6}\s+/, '').trim();
      continue;
    }
    if ((buf + '\n' + line).length > CHUNK_SIZE) {
      flush();
      buf = (buf.slice(-CHUNK_OVERLAP) + ' ' + line).trim();
    } else {
      buf = buf ? buf + '\n' + line : line;
    }
  }
  flush();
  return out;
}

async function embedAll(texts: string[]): Promise<(number[] | null)[]> {
  const c = client();
  if (!c) return texts.map(() => null);
  try {
    const r = await c.embeddings.create({ model: 'text-embedding-3-small', input: texts });
    return r.data.map((d) => d.embedding as number[]);
  } catch {
    return texts.map(() => null);
  }
}

function cosine(a: number[], b: number[]): number {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return na > 0 && nb > 0 ? dot / (Math.sqrt(na) * Math.sqrt(nb)) : 0;
}

export async function ingestDocument(args: { org_id: string; filename: string; text: string }) {
  const doc_id = randomUUID();
  DOCS.push({ id: doc_id, org_id: args.org_id, filename: args.filename, uploaded_at: new Date().toISOString() });
  const segs = chunkText(args.text);
  const embeds = await embedAll(segs.map((s) => s.text));
  segs.forEach((s, i) => {
    CHUNKS.push({
      id: randomUUID(),
      doc_id,
      org_id: args.org_id,
      filename: args.filename,
      heading: s.heading,
      text: s.text,
      embedding: embeds[i],
      ord: i,
    });
  });
  return { doc_id, chunk_count: segs.length };
}

export function listDocuments(org_id: string) {
  return DOCS.filter((d) => d.org_id === org_id).map((d) => ({
    ...d,
    chunk_count: CHUNKS.filter((c) => c.doc_id === d.id).length,
  }));
}

export async function retrieve(args: { org_id: string; query: string; top_k: number }) {
  const candidates = CHUNKS.filter((c) => c.org_id === args.org_id);
  if (candidates.length === 0) return { chunks: [] };

  const c = client();
  if (c) {
    try {
      const q = await c.embeddings.create({ model: 'text-embedding-3-small', input: args.query });
      const qv = q.data[0].embedding as number[];
      const scored = candidates
        .filter((x) => x.embedding)
        .map((x) => ({ x, score: cosine(qv, x.embedding!) }))
        .sort((a, b) => b.score - a.score)
        .slice(0, args.top_k ?? 3);
      return {
        chunks: scored.map((s) => ({
          text: s.x.text,
          filename: s.x.filename,
          heading: s.x.heading,
          score: Number(s.score.toFixed(3)),
        })),
      };
    } catch {
      /* fall through to keyword */
    }
  }

  // Keyword fallback
  const terms = args.query
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length >= 3);
  const scored = candidates
    .map((x) => {
      const hay = (x.text + ' ' + x.filename + ' ' + (x.heading ?? '')).toLowerCase();
      const score = terms.reduce((a, t) => a + (hay.includes(t) ? 1 : 0), 0) / Math.max(1, terms.length);
      return { x, score };
    })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, args.top_k ?? 3);
  return {
    chunks: scored.map((s) => ({ text: s.x.text, filename: s.x.filename, heading: s.x.heading, score: s.score })),
  };
}
