'use client';

import type { PlanState } from '@/types/plan-state';

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

export async function fetchPlan(id: string): Promise<PlanState> {
  const r = await fetch(`${BASE}/api/plan/${id}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`fetchPlan ${r.status}`);
  return r.json();
}

export async function uploadFiles(id: string, files: File[]): Promise<unknown> {
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
  | { event: 'tool_call'; data: { name: string; args: unknown } }
  | { event: 'message'; data: { role: 'assistant'; text: string } }
  | { event: 'done'; data: 'ok' }
  | { event: 'error'; data: { message: string } };

export async function* streamChat(id: string, message: string): AsyncGenerator<ChatEvent> {
  const r = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ household_id: id, message }),
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
