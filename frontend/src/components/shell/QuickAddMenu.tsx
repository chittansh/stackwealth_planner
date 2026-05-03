'use client';

import { useEffect, useRef, useState } from 'react';
import { Plus, Briefcase, Wallet, Target, Building2, Shield, User, FileUp } from 'lucide-react';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

const ITEMS: { Icon: React.ComponentType<{ size?: number }>; label: string; prompt: string }[] = [
  { Icon: Briefcase, label: 'Add income source', prompt: 'I want to add a new income source — walk me through it.' },
  { Icon: Wallet, label: 'Add a recurring expense', prompt: 'Help me add a recurring monthly expense.' },
  { Icon: Target, label: 'Add a financial goal', prompt: 'I want to add a financial goal — walk me through it.' },
  { Icon: Building2, label: 'Add an asset', prompt: 'Add an asset to my portfolio (cash, FD, mutual fund, equity, real estate).' },
  { Icon: Shield, label: 'Add an insurance policy', prompt: 'Help me capture an insurance policy (term, health, family floater, ULIP).' },
  { Icon: User, label: 'Add a household member', prompt: 'Add another household member (spouse / child / parent) with their DOB and retirement age.' },
];

/**
 * Compact quick-add popover. Each item fires a chat prompt to the planner so
 * the agent walks the user through capture. Also offers a file-upload entry
 * that posts straight to the intake pipeline.
 */
export function QuickAddMenu({ householdId }: { householdId: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const fireChat = (prompt: string) => {
    setOpen(false);
    // Hand off to ChatPanel via a window event — keeps the menu decoupled
    // from the chat panel internals.
    window.dispatchEvent(new CustomEvent('sw:chat-prompt', { detail: { prompt } }));
  };

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setOpen(false);
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append('file', f);
    try {
      await fetch(`${BACKEND}/api/upload/${householdId}`, { method: 'POST', body: fd });
      window.dispatchEvent(
        new CustomEvent('sw:chat-prompt', {
          detail: {
            prompt: `I just uploaded ${files.length} document${files.length > 1 ? 's' : ''}. Walk me through what you extracted and ask me only for what's missing.`,
          },
        }),
      );
    } catch {
      /* surface in chat panel later if needed */
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Quick add"
        className="w-8 h-8 rounded-md border border-zinc-200 grid place-items-center hover:bg-zinc-50 text-zinc-600"
      >
        <Plus size={14} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 w-[240px] rounded-lg border border-zinc-200 bg-white shadow-md py-1">
          {ITEMS.map(({ Icon, label, prompt }) => (
            <button
              key={label}
              onClick={() => fireChat(prompt)}
              className="w-full text-left px-2.5 py-1.5 text-[13px] text-zinc-700 hover:bg-zinc-50 inline-flex items-center gap-2"
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
          <div className="my-1 border-t border-zinc-100" />
          <button
            onClick={() => fileRef.current?.click()}
            className="w-full text-left px-2.5 py-1.5 text-[13px] text-zinc-700 hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <FileUp size={13} />
            Upload a document
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = e.target.files;
              e.target.value = '';
              void upload(files);
            }}
          />
        </div>
      )}
    </div>
  );
}
