'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  Users,
  Activity,
  Bell,
  ArrowUpRight,
} from 'lucide-react';
import { formatINR } from '@/lib/utils';
import { createHousehold } from '@/lib/api';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';
const PAGE_SIZE = 5;

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
  const [search, setSearch] = useState('');
  const formRef = useRef<HTMLFormElement>(null);

  const load = useCallback(async (pageOffset: number) => {
    setBusy(true);
    try {
      const j = await fetch(`${BACKEND}/api/advisor/clients?limit=${PAGE_SIZE}&offset=${pageOffset}`).then((r) =>
        r.json(),
      );
      setRows(j.rows ?? []);
      setTotal(j.total ?? 0);
    } catch {
      setRows([]);
      setTotal(0);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load(offset);
  }, [load, offset]);

  useEffect(() => {
    if (creating) requestAnimationFrame(() => formRef.current?.querySelector('input')?.focus());
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

  // Filter visible rows by search query (matches name / household_id).
  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.name.toLowerCase().includes(q) || r.household_id.toLowerCase().includes(q));
  }, [rows, search]);

  // Derived stats — averaged across the current page so they're cheap.
  const stats = useMemo(() => {
    const scored = rows.filter((r) => r.freedom_score != null);
    const avgScore = scored.length
      ? scored.reduce((s, r) => s + (r.freedom_score ?? 0), 0) / scored.length
      : null;
    const lowScore = scored.filter((r) => (r.freedom_score ?? 0) < 50).length;
    const totalNews = rows.reduce((s, r) => s + r.news_count, 0);
    return { avgScore, lowScore, totalNews };
  }, [rows]);

  return (
    <div className="flex flex-col gap-5">
      {/* ── Stats overview ────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          icon={Users}
          label="Total clients"
          value={total > 0 ? String(total) : busy ? '…' : String(rows.length)}
        />
        <StatTile
          icon={Activity}
          label="Avg Freedom Score"
          value={stats.avgScore != null ? stats.avgScore.toFixed(0) : busy ? '…' : '—'}
          suffix={stats.avgScore != null ? '/100' : undefined}
          tone={stats.avgScore != null ? (stats.avgScore >= 75 ? 'good' : stats.avgScore >= 50 ? 'warn' : 'bad') : undefined}
        />
        <StatTile
          icon={Activity}
          label="At-risk clients"
          value={busy ? '…' : String(stats.lowScore)}
          suffix={stats.lowScore > 0 ? 'score < 50' : undefined}
          tone={stats.lowScore > 0 ? 'warn' : 'good'}
        />
        <StatTile
          icon={Bell}
          label="News alerts"
          value={busy ? '…' : String(stats.totalNews)}
          suffix={stats.totalNews > 0 ? 'unread' : undefined}
        />
      </div>

      {/* ── Toolbar (search + new client) ──────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-[340px]">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400 pointer-events-none"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or household ID…"
            className="w-full h-9 pl-9 pr-3 text-sm rounded-lg border border-zinc-200 bg-white outline-none placeholder:text-zinc-400 focus:border-zinc-400"
          />
        </div>
        <div className="text-xs text-zinc-500 hidden md:block">
          {total === 0
            ? `${rows.length} client${rows.length === 1 ? '' : 's'}`
            : `Showing ${offset + 1}–${offset + rows.length} of ${total}`}
        </div>
        <div className="flex-1" />
        {!creating ? (
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 text-sm px-3.5 h-9 rounded-lg text-white font-medium shadow-sm hover:shadow transition-shadow"
            style={{ background: 'var(--color-accent)' }}
          >
            <Plus size={14} /> New client
          </button>
        ) : (
          <form ref={formRef} onSubmit={submit} className="inline-flex items-center gap-1.5">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  setCreating(false);
                  setName('');
                }
              }}
              placeholder="Client name (e.g. Sharma Family)"
              className="text-sm h-9 px-3 w-[260px] rounded-lg border border-zinc-200 outline-none focus:border-zinc-400"
            />
            <button
              type="submit"
              disabled={!name.trim()}
              className="text-sm px-3.5 h-9 rounded-lg text-white font-medium disabled:opacity-50"
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
              className="text-sm px-3 h-9 rounded-lg text-zinc-500 hover:text-zinc-900 hover:bg-zinc-50"
            >
              Cancel
            </button>
          </form>
        )}
      </div>

      {/* ── List ───────────────────────────────────────────────────── */}
      {busy && rows.length === 0 ? (
        <SkeletonGrid />
      ) : visibleRows.length === 0 ? (
        rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-200 p-12 text-center">
            <div className="mx-auto w-12 h-12 rounded-full bg-zinc-100 grid place-items-center mb-3">
              <Users size={20} className="text-zinc-400" />
            </div>
            <p className="text-sm text-zinc-700 font-medium">No clients yet</p>
            <p className="text-xs text-zinc-500 mt-1">
              Click <span className="text-zinc-700 font-medium">+ New client</span> to start one.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-center text-sm text-zinc-500">
            No clients match <span className="text-zinc-800">&ldquo;{search}&rdquo;</span>.
          </div>
        )
      ) : (
        <div className="rounded-xl border border-zinc-200 bg-white overflow-hidden">
          <div className="hidden md:grid grid-cols-[1.5fr_120px_1fr_1fr_100px_44px] gap-4 px-5 py-2.5 text-[10px] uppercase tracking-wide text-zinc-500 bg-zinc-50/60 border-b border-zinc-100">
            <span>Household</span>
            <span className="text-right">Freedom Score</span>
            <span>Projection (45y)</span>
            <span>Biggest gap</span>
            <span>Last activity</span>
            <span />
          </div>
          <ul className="divide-y divide-zinc-100">
            {visibleRows.map((r) => (
              <li key={r.household_id}>
                <Link
                  href={`/plan/${r.household_id}`}
                  className="block px-5 py-3.5 hover:bg-zinc-50/60 transition-colors group"
                >
                  {/* Desktop layout */}
                  <div className="hidden md:grid grid-cols-[1.5fr_120px_1fr_1fr_100px_44px] gap-4 items-center">
                    <div className="flex items-center gap-3 min-w-0">
                      <Avatar name={r.name} />
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-zinc-900 truncate">
                          {r.name}
                          {r.news_count > 0 && (
                            <span className="ml-2 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-amber-50 text-amber-700 text-[10px] font-medium">
                              {r.news_count}
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-zinc-400 font-mono truncate">{r.household_id}</div>
                      </div>
                    </div>
                    <div className="text-right">
                      <ScoreChip n={r.freedom_score} />
                    </div>
                    <div className="text-sm tabular-nums text-zinc-700">
                      {r.headline ? formatINR(r.headline, { compact: true }) : <span className="text-zinc-400">—</span>}
                    </div>
                    <div className="text-xs text-zinc-600 truncate">{r.biggest_gap}</div>
                    <div className="text-xs text-zinc-500 truncate">{r.last_activity}</div>
                    <div className="text-zinc-300 group-hover:text-zinc-700 transition-colors">
                      <ArrowUpRight size={16} />
                    </div>
                  </div>

                  {/* Mobile stacked layout */}
                  <div className="md:hidden flex gap-3">
                    <Avatar name={r.name} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-sm font-medium text-zinc-900 truncate">{r.name}</span>
                        <ScoreChip n={r.freedom_score} />
                      </div>
                      <div className="flex items-baseline justify-between gap-2 mt-1">
                        <span className="text-xs text-zinc-500 truncate">{r.biggest_gap}</span>
                        <span className="text-xs tabular-nums text-zinc-600 whitespace-nowrap">
                          {r.headline ? formatINR(r.headline, { compact: true }) : '—'}
                        </span>
                      </div>
                      <div className="text-[10px] text-zinc-400 mt-1">{r.last_activity}</div>
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Pagination ─────────────────────────────────────────────── */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-zinc-600">
          <button
            disabled={offset === 0 || busy}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="inline-flex items-center gap-1 px-3 h-8 rounded-lg border border-zinc-200 bg-white disabled:opacity-40 hover:bg-zinc-50 transition-colors"
          >
            <ChevronLeft size={13} /> Prev
          </button>
          <span className="tabular-nums text-zinc-500">
            Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
          </span>
          <button
            disabled={offset + PAGE_SIZE >= total || busy}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="inline-flex items-center gap-1 px-3 h-8 rounded-lg border border-zinc-200 bg-white disabled:opacity-40 hover:bg-zinc-50 transition-colors"
          >
            Next <ChevronRight size={13} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Pieces ─────────────────────────────────────────────────────────── */

function StatTile({
  icon: Icon,
  label,
  value,
  suffix,
  tone,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: string;
  suffix?: string;
  tone?: 'good' | 'warn' | 'bad';
}) {
  const accent =
    tone === 'good'
      ? 'text-[color:var(--color-accent,#5f7d56)]'
      : tone === 'warn'
      ? 'text-amber-700'
      : tone === 'bad'
      ? 'text-rose-700'
      : 'text-zinc-900';
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
        <Icon size={11} />
        {label}
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className={`text-2xl font-semibold tabular-nums ${accent}`}>{value}</span>
        {suffix && <span className="text-[10px] text-zinc-400">{suffix}</span>}
      </div>
    </div>
  );
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/[\s,/]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? '')
    .join('') || '?';
  // Stable hue from the name so each client keeps the same colour.
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;
  return (
    <div
      className="shrink-0 w-9 h-9 rounded-full grid place-items-center text-[11px] font-medium text-white shadow-sm"
      style={{ background: `linear-gradient(135deg, hsl(${hue} 35% 50%), hsl(${(hue + 30) % 360} 35% 42%))` }}
      aria-hidden
    >
      {initials}
    </div>
  );
}

function ScoreChip({ n }: { n: number | null }) {
  if (n == null) return <span className="text-zinc-300 text-xs">—</span>;
  const tone = n >= 75 ? 'good' : n >= 50 ? 'mid' : 'low';
  const cls =
    tone === 'good'
      ? 'bg-[var(--color-accent-soft,#eef3eb)] text-[color:var(--color-accent,#5f7d56)]'
      : tone === 'mid'
      ? 'bg-amber-50 text-amber-700'
      : 'bg-rose-50 text-rose-700';
  return (
    <span className={`inline-flex items-baseline gap-0.5 px-2 py-0.5 rounded-md text-xs tabular-nums font-medium ${cls}`}>
      {n.toFixed(0)}
      <span className="text-[9px] opacity-60">/100</span>
    </span>
  );
}

function SkeletonGrid() {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white overflow-hidden">
      <ul className="divide-y divide-zinc-100">
        {Array.from({ length: 6 }).map((_, i) => (
          <li key={i} className="px-5 py-3.5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-zinc-100 animate-pulse" />
            <div className="flex-1 flex flex-col gap-1.5">
              <div className="h-3 bg-zinc-100 rounded animate-pulse w-40" />
              <div className="h-2.5 bg-zinc-50 rounded animate-pulse w-24" />
            </div>
            <div className="h-5 w-16 rounded-md bg-zinc-100 animate-pulse" />
            <div className="h-3 w-20 bg-zinc-100 rounded animate-pulse hidden md:block" />
            <div className="h-3 w-24 bg-zinc-100 rounded animate-pulse hidden md:block" />
          </li>
        ))}
      </ul>
    </div>
  );
}
