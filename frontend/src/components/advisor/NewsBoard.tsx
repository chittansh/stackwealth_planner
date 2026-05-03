'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type Item = {
  id: string;
  title: string;
  summary: string;
  sectors: string[];
  published_at: string;
  affected: { household_id: string; name: string; relevance: number; rationale: string }[];
};

export function NewsBoard() {
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND}/api/news`)
      .then((r) => r.json())
      .then((j) => setItems(j.items ?? []))
      .catch(() => setItems([]))
      .finally(() => setBusy(false));
  }, []);

  if (busy) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (!items.length) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        No news items yet. Wire up a fetcher (or POST to <code className="text-zinc-700">/api/news</code>)
        to populate this board.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {items.map((n) => (
        <article key={n.id} className="rounded-xl border border-zinc-200 bg-white p-5">
          <header className="mb-2">
            <h3 className="text-sm font-medium text-zinc-800">{n.title}</h3>
            <p className="text-[11px] text-zinc-400">
              {new Date(n.published_at).toLocaleDateString()} · sectors: {n.sectors.join(', ') || '—'}
            </p>
          </header>
          <p className="text-sm text-zinc-600 mb-3">{n.summary}</p>
          {n.affected.length === 0 ? (
            <p className="text-xs text-zinc-400">No clients materially affected.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {n.affected.map((a) => (
                <li key={a.household_id} className="flex items-center gap-2 text-xs">
                  <span className="inline-flex items-center justify-center w-7 h-5 rounded bg-zinc-100 text-zinc-700 text-[10px] tabular-nums">
                    {a.relevance.toFixed(2)}
                  </span>
                  <Link href={`/plan/${a.household_id}`} className="text-zinc-700 hover:underline">
                    {a.name}
                  </Link>
                  <span className="text-zinc-400">— {a.rationale}</span>
                </li>
              ))}
            </ul>
          )}
        </article>
      ))}
    </div>
  );
}
