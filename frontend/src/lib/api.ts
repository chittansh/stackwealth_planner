'use client';

import type { PlanState } from '@/types/plan-state';

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

export async function fetchPlan(id: string): Promise<PlanState> {
  const r = await fetch(`${BASE}/api/plan/${id}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`fetchPlan ${r.status}`);
  return r.json();
}

export type UploadSummary = {
  filename: string;
  parser_used: string;
  sections_set: string[];
  list_rows_added: number;
  fields_extracted: number;
  missing: string[];
  error?: string;
};

export async function uploadFiles(
  id: string,
  files: File[],
): Promise<{ ok: boolean; summaries: UploadSummary[] }> {
  const fd = new FormData();
  for (const f of files) fd.append('file', f);
  const r = await fetch(`${BASE}/api/upload/${id}`, { method: 'POST', body: fd });
  if (!r.ok) throw new Error(`uploadFiles ${r.status}`);
  return r.json();
}

export async function uploadText(id: string, text: string, source_type: 'user' | 'transcript' | 'md' = 'user') {
  const r = await fetch(`${BASE}/api/upload/${id}/text`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text, source_type }),
  });
  if (!r.ok) throw new Error(`uploadText ${r.status}`);
  return r.json();
}

export type ChatEvent =
  | { event: 'status'; data: string }
  | { event: 'tool_call'; data: { id: string; name: string; args: unknown } }
  | { event: 'tool_result'; data: { id: string; name: string; result: unknown } }
  | {
      event: 'trace';
      data: { trace_id: string; observation_id?: string; turn?: number };
    }
  | { event: 'message'; data: { role: 'assistant'; text: string } }
  | { event: 'done'; data: 'ok' }
  | { event: 'error'; data: { message: string } };

export async function* streamChat(
  id: string,
  message: string,
  chatId?: string,
): AsyncGenerator<ChatEvent> {
  const r = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ household_id: id, message, chat_id: chatId }),
  });
  if (!r.body) throw new Error('chat: no body');

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const lines = raw.split('\n');
      let event = 'message';
      let data = '';
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      try {
        const parsed = data && (data.startsWith('{') || data.startsWith('[')) ? JSON.parse(data) : data;
        yield { event, data: parsed } as ChatEvent;
      } catch {
        yield { event, data } as ChatEvent;
      }
    }
  }
}

export async function planSet(id: string, path: string, value: unknown) {
  return fetch(`${BASE}/api/plan/${id}/set`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path, value }),
  }).then((r) => r.json());
}

export async function resetChat(id: string, chatId?: string) {
  const qs = chatId ? `?chat_id=${encodeURIComponent(chatId)}` : '';
  return fetch(`${BASE}/api/chat/${id}/reset${qs}`, { method: 'POST' }).then((r) => r.json());
}

export async function hydrateChat(
  id: string,
  chatId: string | undefined,
  turns: { role: 'user' | 'assistant'; text: string }[],
) {
  const qs = chatId ? `?chat_id=${encodeURIComponent(chatId)}` : '';
  return fetch(`${BASE}/api/chat/${id}/hydrate${qs}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ turns }),
  }).then((r) => r.json());
}

export type FeedbackBody = {
  trace_id: string;
  observation_id?: string;
  value: number; // 1 = thumbs up, -1 = thumbs down
  comment?: string;
  household_id?: string;
  chat_id?: string;
  turn?: number;
};

export async function submitFeedback(
  body: FeedbackBody,
): Promise<{ ok: boolean; recorded?: boolean; error?: string }> {
  const r = await fetch(`${BASE}/api/feedback`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    return { ok: false, error: text || `HTTP ${r.status}` };
  }
  return r.json();
}

export async function createHousehold(name: string, advisorId?: string): Promise<{ id: string }> {
  const r = await fetch(`${BASE}/api/plan`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, advisor_id: advisorId }),
  });
  if (!r.ok) throw new Error(`createHousehold ${r.status}`);
  return r.json();
}
