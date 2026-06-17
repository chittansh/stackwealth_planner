'use client';

/**
 * Per-household chat store backed by localStorage.
 *
 *   sw.chats.<household_id> → { activeChatId, chats: { [chat_id]: ChatRecord } }
 *
 * Each chat carries its own message list + a derived title (first user line).
 * Plan data lives on the backend; only chat UX state is persisted client-side.
 */

import { useCallback, useEffect, useState } from 'react';

export type StoredMsg = {
  // We mirror the ChatPanel `Msg` shape, but `kind` is always present.
  // Stored as-is so a reload restores the exact rendering state.
  kind: 'user' | 'status' | 'thinking' | 'tool' | 'assistant' | 'risk_gate';
  // Discriminated fields — at most one of these is meaningful per kind.
  text?: string;
  files?: { name: string; size: number }[];
  id?: string;
  name?: string;
  args?: unknown;
  result?: unknown;
  state?: 'running' | 'done' | 'error';
  // Langfuse trace pointers, attached to assistant messages so the user can
  // submit thumbs-up/down feedback that hits the right turn observation.
  traceId?: string;
  observationId?: string;
  turn?: number;
  // The feedback the user already submitted on this message (1 / -1) — drives
  // the "submitted" UI state on reload.
  feedback?: 1 | -1;
  feedbackComment?: string;
};

export type ChatRecord = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  messages: StoredMsg[];
};

type Bucket = {
  active_chat_id: string;
  chats: Record<string, ChatRecord>;
};

const KEY = (householdId: string) => `sw.chats.${householdId}`;
const VERSION = 1; // bump to invalidate old shapes

function read(householdId: string): Bucket {
  if (typeof window === 'undefined') return blankBucket();
  try {
    const raw = window.localStorage.getItem(KEY(householdId));
    if (!raw) return blankBucket();
    const parsed = JSON.parse(raw) as { v: number; bucket: Bucket };
    if (parsed.v !== VERSION) return blankBucket();
    return parsed.bucket;
  } catch {
    return blankBucket();
  }
}

function write(householdId: string, bucket: Bucket) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(KEY(householdId), JSON.stringify({ v: VERSION, bucket }));
  } catch {
    /* quota / private mode — silently drop */
  }
}

function blankBucket(): Bucket {
  const id = newChatId();
  return {
    active_chat_id: id,
    chats: { [id]: { id, title: 'New chat', created_at: Date.now(), updated_at: Date.now(), messages: [] } },
  };
}

export function newChatId(): string {
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function deriveTitle(messages: StoredMsg[]): string {
  const firstUser = messages.find((m) => m.kind === 'user' && m.text);
  if (!firstUser?.text) return 'New chat';
  const t = firstUser.text.trim().split('\n')[0];
  return t.length > 40 ? `${t.slice(0, 40)}…` : t;
}

export function useChatStore(householdId: string) {
  const [bucket, setBucket] = useState<Bucket>(blankBucket);
  const [hydrated, setHydrated] = useState(false);

  // Load from localStorage on mount / household switch.
  useEffect(() => {
    setBucket(read(householdId));
    setHydrated(true);
  }, [householdId]);

  // Persist on change.
  useEffect(() => {
    if (!hydrated) return;
    write(householdId, bucket);
  }, [householdId, bucket, hydrated]);

  const activeChatId = bucket.active_chat_id;
  const activeChat = bucket.chats[activeChatId];
  const chatList = Object.values(bucket.chats).sort((a, b) => b.updated_at - a.updated_at);

  const setMessages = useCallback((updater: (prev: StoredMsg[]) => StoredMsg[]) => {
    setBucket((prev) => {
      const cur = prev.chats[prev.active_chat_id];
      const nextMessages = updater(cur?.messages ?? []);
      const nextChat: ChatRecord = {
        ...cur,
        id: prev.active_chat_id,
        created_at: cur?.created_at ?? Date.now(),
        messages: nextMessages,
        updated_at: Date.now(),
        title: deriveTitle(nextMessages),
      };
      return { ...prev, chats: { ...prev.chats, [prev.active_chat_id]: nextChat } };
    });
  }, []);

  const newChat = useCallback(() => {
    const id = newChatId();
    setBucket((prev) => ({
      active_chat_id: id,
      chats: {
        ...prev.chats,
        [id]: { id, title: 'New chat', created_at: Date.now(), updated_at: Date.now(), messages: [] },
      },
    }));
    return id;
  }, []);

  const switchChat = useCallback((id: string) => {
    setBucket((prev) => (prev.chats[id] ? { ...prev, active_chat_id: id } : prev));
  }, []);

  /** Replace the entire bucket with a server-side hydration: a list of
   * conversations (chat_id + title) and the messages for the
   * most-recent one. Used on household open to "remember" the last
   * conversation across browsers / devices / deploys. */
  const syncFromServer = useCallback(
    (args: {
      conversations: { chat_id: string; title: string; last_active: string | null }[];
      activeId: string;
      activeMessages: StoredMsg[];
    }) => {
      setBucket((prev) => {
        const chats: Record<string, ChatRecord> = {};
        for (const c of args.conversations) {
          // Preserve any locally-cached messages we already have for this
          // chat so unsent / in-flight UI state isn't lost on rehydrate.
          // For the activeId, the server's authoritative message list
          // wins so the user sees their full history.
          const existing = prev.chats[c.chat_id];
          chats[c.chat_id] = {
            id: c.chat_id,
            title: c.title || 'New chat',
            created_at: existing?.created_at ?? Date.now(),
            updated_at: c.last_active ? new Date(c.last_active).getTime() : Date.now(),
            messages: c.chat_id === args.activeId ? args.activeMessages : existing?.messages ?? [],
          };
        }
        // Keep any locally-only chats that haven't synced yet (e.g. a
        // brand-new "New chat" the user just opened with no DB rows).
        for (const [id, record] of Object.entries(prev.chats)) {
          if (!chats[id]) chats[id] = record;
        }
        const nextActive = chats[args.activeId] ? args.activeId : prev.active_chat_id;
        return { active_chat_id: nextActive, chats };
      });
    },
    [],
  );

  const deleteChat = useCallback((id: string) => {
    setBucket((prev) => {
      const { [id]: _, ...rest } = prev.chats;
      const remaining = Object.keys(rest);
      if (remaining.length === 0) return blankBucket();
      const nextActive = prev.active_chat_id === id ? remaining[0] : prev.active_chat_id;
      return { active_chat_id: nextActive, chats: rest };
    });
  }, []);

  return {
    hydrated,
    activeChatId,
    activeChat,
    chatList,
    messages: activeChat?.messages ?? [],
    setMessages,
    newChat,
    switchChat,
    syncFromServer,
    deleteChat,
  };
}
