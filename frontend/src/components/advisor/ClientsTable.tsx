'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { formatINR } from '@/lib/utils';
import { createHousehold } from '@/lib/api';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';
const PAGE_SIZE = 25;

type Row = {
  household_id: string;
  name: string;
  freedom_score: number | null;
  headline: number | null;
  biggest_gap: string;
  last_activity: string;
  news_count: number;
};

export function ClientsTable() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const formRef = useRef<HTMLFormElement>(null);

  const load = useCallback(
    async (pageOffset: number) => {
      setBusy(true);
      try {
        const j = await fetch(
          `${BACKEND}/api/advisor/clients?limit=${PAGE_SIZE}&offset=${pageOffset}`,
        ).then((r) => r.json());
        setRows(j.rows ?? []);
        setTotal(j.total ?? 0);
      } catch {
        setRows([]);
        setTotal(0);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    load(offset);
  }, [load, offset]);

  useEffect(() => {
    if (creating) {
      // Focus the input as soon as the form opens.
      requestAnimationFrame(() => formRef.current?.querySelector('input')?.focus());
    }
  }, [creating]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const { id } = await createHousehold(trimmed);
      router.push(`/plan/${id}`);
    } catch {
      window.dispatchEvent(new CustomEvent('sw:toast', { detail: { text: 'Could not create client' } }));
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-zinc-500">
          {total === 0
            ? `${rows.length} client${rows.length === 1 ? '' : 's'}`
            : `Showing ${offset + 1}–${offset + rows.length} of ${total}`}
        </p>
        {!creating ? (
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 text-xs px-3 h-8 rounded-md text-white"
            style={{ background: 'var(--color-accent)' }}
          >
            <Plus size={13} /> New client
          </button>
        ) : (
          <form ref={formRef} onSubmit={submit} className="inline-flex items-center gap-1">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && (setCreating(false), setName(''))}
              placeholder="Client name (e.g. Sharma Family)"
              className="text-xs h-8 px-2.5 w-[260px] rounded-md border border-zinc-200 outline-none focus:border-zinc-400"
            />
            <button
              type="submit"
              disabled={!name.trim()}
              className="text-xs px-3 h-8 rounded-md text-white disabled:opacity-50"
              style={{ background: 'var(--color-accent)' }}
            >
              Create
            </button>
            <button
              type="button"
              onClick={() => {
                setCreating(false);
                setName('');
              }}
              className="text-xs px-2 h-8 rounded-md text-zinc-500 hover:text-zinc-900"
            >
              Cancel
            </button>
          </form>
        )}
      </div>

      {busy ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
          No clients yet. Click <span className="text-zinc-700">+ New client</span> to start one.
        </div>
      ) : (
        <div className="rounded-xl border border-zinc-200 overflow-hidden bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-zinc-50 text-zinc-500 text-xs uppercase tracking-wide">
              <tr>
                <Th>Household</Th>
                <Th right>Freedom Score</Th>
                <Th right>Projection (45y)</Th>
                <Th>Biggest gap</Th>
                <Th>Last activity</Th>
                <Th right>News</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.household_id} className="border-t border-zinc-100 hover:bg-zinc-50/60">
                  <td className="px-4 py-2.5">
                    <Link href={`/plan/${r.household_id}`} className="text-zinc-900 hover:underline">
                      {r.name}
                    </Link>
                    <div className="text-[10px] text-zinc-400 font-mono">{r.household_id}</div>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {r.freedom_score == null ? <span className="text-zinc-400">—</span> : <Score n={r.freedom_score} />}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {r.headline ? formatINR(r.headline, { compact: true }) : <span className="text-zinc-400">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-zinc-600">{r.biggest_gap}</td>
                  <td className="px-4 py-2.5 text-zinc-500">{r.last_activity}</td>
                  <td className="px-4 py-2.5 text-right">
                    {r.news_count > 0 ? (
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-zinc-100 text-zinc-700 text-[11px]">
                        {r.news_count}
                      </span>
                    ) : (
                      <span className="text-zinc-300 text-xs">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-zinc-600 mt-1">
          <button
            disabled={offset === 0 || busy}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="inline-flex items-center gap-1 px-2.5 h-8 rounded-md border border-zinc-200 disabled:opacity-40 hover:bg-zinc-50"
          >
            <ChevronLeft size={13} /> Prev
          </button>
          <span className="tabular-nums text-zinc-500">
            Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
          </span>
          <button
            disabled={offset + PAGE_SIZE >= total || busy}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="inline-flex items-center gap-1 px-2.5 h-8 rounded-md border border-zinc-200 disabled:opacity-40 hover:bg-zinc-50"
          >
            Next <ChevronRight size={13} />
          </button>
        </div>
      )}
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-4 py-2.5 font-medium ${right ? 'text-right' : 'text-left'}`}>{children}</th>;
}

function Score({ n }: { n: number }) {
  const style: React.CSSProperties = n >= 75 ? { color: 'var(--color-accent)' } : { color: '#3f3f46' };
  return <span style={style}>{n.toFixed(0)}</span>;
}
