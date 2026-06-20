'use client';

import type { PlanState } from '@/types/plan-state';

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

export async function fetchPlan(id: string): Promise<PlanState> {
  // Backend may return 503 with Retry-After header on transient PG
  // flaps. Retry once after the suggested delay (or 2s default) so a
  // brief mesh blip doesn't surface as a hard error in the canvas.
  let r = await fetch(`${BASE}/api/plan/${id}`, { cache: 'no-store' });
  if (r.status === 503) {
    const retryAfter = Number(r.headers.get('Retry-After') ?? '2');
    await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));
    r = await fetch(`${BASE}/api/plan/${id}`, { cache: 'no-store' });
  }
  if (!r.ok) throw new Error(`fetchPlan ${r.status}`);
  return r.json();
}

export type Anomaly = {
  severity: 'high' | 'medium' | 'low';
  category: 'surplus' | 'income' | 'expense' | 'retirement' | 'insurance' | 'emergency' | 'data';
  field: string;
  value: unknown;
  message: string;
  question: string;
};

export type UploadSummary = {
  filename: string;
  parser_used: string;
  sections_set: string[];
  list_rows_added: number;
  fields_extracted: number;
  missing: string[];
  error?: string;
  anomalies?: Anomaly[];
};

export type UploadStreamEvent =
  | { event: 'file_started'; filename: string; size: number }
  | { event: 'parsing'; parser_hint: string; filename: string }
  | { event: 'heartbeat'; stage: string; elapsed_ms: number; filename: string }
  | { event: 'parsed'; parser_used: string; field_count: number; filename: string }
  | { event: 'field'; path: string; value: unknown; ok: true }
  | { event: 'row_added'; path: string; row_id?: string; label?: string }
  | { event: 'rejected'; path: string; reason: string }
  | { event: 'fsi_synced'; derived: Record<string, number>; filename: string }
  | { event: 'anomalies_detected'; count: number }
  | { event: 'file_done'; summary: UploadSummary }
  | { event: 'done'; summaries: UploadSummary[] };

/**
 * Stream NDJSON events from the upload endpoint. Each yield is a parsed event;
 * the caller updates UI as they arrive (live "extracted N fields..." status
 * instead of a dead spinner).
 */
export async function* uploadFiles(
  id: string,
  files: File[],
): AsyncGenerator<UploadStreamEvent, void, void> {
  const fd = new FormData();
  for (const f of files) fd.append('file', f);
  const r = await fetch(`${BASE}/api/upload/${id}`, { method: 'POST', body: fd });
  if (!r.ok) throw new Error(`uploadFiles ${r.status}`);
  if (!r.body) throw new Error('uploadFiles: empty response body');
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      try {
        yield JSON.parse(line) as UploadStreamEvent;
      } catch {
        // tolerate partial / malformed lines
      }
    }
  }
  // Flush any final unterminated line.
  const tail = buf.trim();
  if (tail) {
    try { yield JSON.parse(tail) as UploadStreamEvent; } catch { /* ignore */ }
  }
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
  displayMessage?: string,
): AsyncGenerator<ChatEvent> {
  const r = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ household_id: id, message, chat_id: chatId, display_message: displayMessage }),
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

export async function fetchSuggestions(id: string): Promise<unknown> {
  const r = await fetch(`${BASE}/api/skill/suggestions/${id}`, { method: 'POST' });
  if (!r.ok) throw new Error(`fetchSuggestions ${r.status}`);
  return r.json();
}

export async function fetchScenariosV2(id: string, overrides?: Record<string, unknown>): Promise<unknown> {
  const r = await fetch(`${BASE}/api/skill/scenarios/${id}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(overrides ? { overrides } : {}),
  });
  if (!r.ok) throw new Error(`fetchScenariosV2 ${r.status}`);
  return r.json();
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

export type ServerConversation = {
  chat_id: string;
  title: string;
  last_active: string | null;
  message_count: number;
};

/** List all conversations for a household, most-recent first. Returns
 * empty array when DB is unconfigured (dev / local). */
export async function listConversations(id: string): Promise<ServerConversation[]> {
  try {
    const r = await fetch(`${BASE}/api/chat/${id}/conversations`, { cache: 'no-store' });
    if (!r.ok) return [];
    const body = (await r.json()) as { conversations: ServerConversation[] };
    return body.conversations ?? [];
  } catch {
    return [];
  }
}

export type ServerChatMessage = { role: 'user' | 'assistant'; text: string; turn: number | null };

/** Load chronological message history for a (household, chat_id) pair. */
export async function fetchChatHistory(
  id: string,
  chatId: string | undefined,
): Promise<ServerChatMessage[]> {
  try {
    const qs = chatId ? `?chat_id=${encodeURIComponent(chatId)}` : '';
    const r = await fetch(`${BASE}/api/chat/${id}/history${qs}`, { cache: 'no-store' });
    if (!r.ok) return [];
    const body = (await r.json()) as { messages: ServerChatMessage[] };
    return body.messages ?? [];
  } catch {
    return [];
  }
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
