'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, MessageSquare, Trash2 } from 'lucide-react';
import type { ChatRecord } from '@/lib/chatStore';

/**
 * Compact chat picker — shows the active chat's title and pops a dropdown
 * with the rest, ordered by recency. Each row has a small delete affordance.
 */
export function ChatSwitcher({
  chats,
  activeId,
  onPick,
  onDelete,
}: {
  chats: ChatRecord[];
  activeId: string;
  onPick: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = chats.find((c) => c.id === activeId);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-900 px-1.5 h-6 rounded-md hover:bg-zinc-50 max-w-[140px]"
        title="Switch chat"
      >
        <MessageSquare size={11} className="shrink-0" />
        <span className="truncate">{active?.title ?? 'New chat'}</span>
        <ChevronDown size={11} className="shrink-0 text-zinc-300" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-[240px] z-30 rounded-lg border border-zinc-200 bg-white shadow-md py-1 max-h-[280px] overflow-y-auto">
          {chats.length === 0 && (
            <div className="px-3 py-2 text-xs text-zinc-400">No chats yet.</div>
          )}
          {chats.map((c) => (
            <div
              key={c.id}
              className={`flex items-center group px-2 py-1.5 ${
                c.id === activeId ? 'bg-[var(--color-accent-soft)]' : 'hover:bg-zinc-50'
              }`}
            >
              <button
                onClick={() => {
                  onPick(c.id);
                  setOpen(false);
                }}
                className="flex-1 min-w-0 text-left"
              >
                <div className="text-[12px] text-zinc-800 truncate">{c.title}</div>
                <div className="text-[10px] text-zinc-400 tabular-nums">
                  {new Date(c.updated_at).toLocaleString('en-IN', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                  {' · '}
                  {c.messages.length} {c.messages.length === 1 ? 'msg' : 'msgs'}
                </div>
              </button>
              {chats.length > 1 && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm('Delete this chat?')) onDelete(c.id);
                  }}
                  className="ml-1 w-6 h-6 grid place-items-center rounded-md text-zinc-300 opacity-0 group-hover:opacity-100 hover:text-zinc-700 hover:bg-zinc-100"
                  title="Delete chat"
                >
                  <Trash2 size={11} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
