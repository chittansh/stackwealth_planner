'use client';

import { useEffect, useState } from 'react';
import { Newspaper, ChevronRight } from 'lucide-react';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type AffectedItem = {
  news_id: string;
  title: string;
  relevance: number;
  rationale: string;
};

/**
 * News strip — sits to the right of the headline. Hits the
 * /api/news/relevance/:id endpoint via the news skill and surfaces the top
 * items that materially affect this household.
 */
export function NewsStrip({ householdId }: { householdId: string }) {
  const [items, setItems] = useState<AffectedItem[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${BACKEND}/api/news`, { cache: 'no-store' });
        const j = (await r.json()) as {
          items: { id: string; title: string; affected: { household_id: string; relevance: number; rationale: string }[] }[];
        };
        const filtered: AffectedItem[] = [];
        for (const it of j.items ?? []) {
          const a = it.affected?.find((x) => x.household_id === householdId);
          if (a && a.relevance >= 0.15) {
            filtered.push({ news_id: it.id, title: it.title, relevance: a.relevance, rationale: a.rationale });
          }
        }
        if (!cancelled) setItems(filtered.sort((a, b) => b.relevance - a.relevance).slice(0, 5));
      } catch {
        /* silent */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [householdId]);

  if (items.length === 0) return null;

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white text-zinc-700 px-2 py-1 text-xs hover:bg-zinc-50"
      >
        <Newspaper size={12} className="text-zinc-400" />
        {items.length} news item{items.length > 1 ? 's' : ''} affecting this household
        <ChevronRight size={12} className={open ? 'rotate-90 transition text-zinc-400' : 'transition text-zinc-400'} />
      </button>
      {open && (
        <ul className="absolute right-0 mt-2 w-[360px] z-30 rounded-lg border border-zinc-200 bg-white shadow-md p-2 text-sm">
          {items.map((it) => (
            <li key={it.news_id} className="px-2 py-1.5 border-b border-zinc-100 last:border-0">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-zinc-800">{it.title}</span>
                <span className="text-[10px] text-zinc-500 tabular-nums">{it.relevance.toFixed(2)}</span>
              </div>
              <p className="text-[11px] text-zinc-500">{it.rationale}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
