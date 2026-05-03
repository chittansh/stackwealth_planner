'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { formatINR } from '@/lib/utils';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

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
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND}/api/advisor/clients`)
      .then((r) => r.json())
      .then((j) => setRows(j.rows ?? []))
      .catch(() => setRows([]))
      .finally(() => setBusy(false));
  }, []);

  if (busy) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        No clients yet. Open <a href="/plan/me" className="text-zinc-700 underline">/plan/me</a> (or any
        <code className="text-zinc-700"> /plan/&lt;id&gt;</code> URL) to create one.
      </div>
    );
  }

  return (
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
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-4 py-2.5 font-medium ${right ? 'text-right' : 'text-left'}`}>{children}</th>;
}

function Score({ n }: { n: number }) {
  // Monochromatic — strong scores get the matcha tint, everything else is plain zinc.
  const style: React.CSSProperties = n >= 75 ? { color: 'var(--color-accent)' } : { color: '#3f3f46' };
  return <span style={style}>{n.toFixed(0)}</span>;
}
