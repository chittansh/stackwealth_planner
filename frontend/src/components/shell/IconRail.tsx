'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import {
  Home,
  Users,
  Combine,
  BookOpen,
  Newspaper,
  Settings,
  RotateCw,
  Trash2,
} from 'lucide-react';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

const NAV: { href: string; label: string; Icon: React.ComponentType<{ size?: number }> }[] = [
  { href: '/plan/me', label: 'My plan', Icon: Home },
  { href: '/advisor/clients', label: 'Clients', Icon: Users },
  { href: '/advisor/household-merge', label: 'Household merge', Icon: Combine },
  { href: '/advisor/knowledge', label: 'Knowledge base', Icon: BookOpen },
  { href: '/advisor/news', label: 'News', Icon: Newspaper },
];

export function IconRail({ householdId }: { householdId: string }) {
  const pathname = usePathname();

  return (
    <aside className="w-[52px] shrink-0 bg-white border-r border-zinc-200 flex flex-col items-center py-3 gap-1">
      <Link
        href="/"
        className="w-7 h-7 rounded-md grid place-items-center font-medium text-[11px] text-white mb-2"
        style={{ background: 'var(--color-accent)' }}
        title="Stackwealth — home"
      >
        SW
      </Link>

      {NAV.map(({ href, label, Icon }) => {
        const active =
          href === '/plan/me' ? pathname?.startsWith('/plan/') : pathname?.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            title={label}
            className={`w-9 h-9 rounded-md grid place-items-center transition ${
              active
                ? 'bg-zinc-100 text-zinc-900'
                : 'text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50'
            }`}
          >
            <Icon size={16} />
          </Link>
        );
      })}

      <SettingsMenu householdId={householdId} />
    </aside>
  );
}

function SettingsMenu({ householdId }: { householdId: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const resetServerConvo = async () => {
    setOpen(false);
    await fetch(`${BACKEND}/api/chat/${householdId}/reset`, { method: 'POST' }).catch(() => undefined);
    window.dispatchEvent(new CustomEvent('sw:toast', { detail: { text: 'Agent context cleared' } }));
  };

  const wipeLocalChats = () => {
    setOpen(false);
    if (!confirm('Delete all locally stored chats for this household?')) return;
    try {
      localStorage.removeItem(`sw.chats.${householdId}`);
      window.dispatchEvent(new CustomEvent('sw:toast', { detail: { text: 'Local chats cleared — refresh' } }));
      setTimeout(() => window.location.reload(), 600);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="mt-auto relative" ref={ref}>
      <button
        title="Settings"
        onClick={() => setOpen((v) => !v)}
        className={`w-9 h-9 rounded-md grid place-items-center transition ${
          open ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50'
        }`}
      >
        <Settings size={16} />
      </button>
      {open && (
        <div className="absolute left-12 bottom-0 z-30 w-[220px] rounded-lg border border-zinc-200 bg-white shadow-md py-1">
          <MenuRow Icon={RotateCw} label="Reset agent context" onClick={resetServerConvo} />
          <MenuRow Icon={Trash2} label="Clear local chat history" onClick={wipeLocalChats} />
          <div className="my-1 border-t border-zinc-100" />
          <p className="px-2.5 py-1 text-[10px] text-zinc-400">household: {householdId}</p>
        </div>
      )}
    </div>
  );
}

function MenuRow({
  Icon,
  label,
  onClick,
}: {
  Icon: React.ComponentType<{ size?: number }>;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left px-2.5 py-1.5 text-[13px] text-zinc-700 hover:bg-zinc-50 inline-flex items-center gap-2"
    >
      <Icon size={13} />
      {label}
    </button>
  );
}
