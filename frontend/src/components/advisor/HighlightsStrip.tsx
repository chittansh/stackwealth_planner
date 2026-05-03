'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { TrendingDown, AlertCircle, Calendar } from 'lucide-react';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type Highlight = {
  kind: 'score_drop' | 'tax_window' | 'news_alert';
  client?: string;
  household_id?: string;
  text: string;
};

const ICON: Record<Highlight['kind'], React.ComponentType<{ size?: number; className?: string }>> = {
  score_drop: TrendingDown,
  news_alert: AlertCircle,
  tax_window: Calendar,
};

const TINT: Record<Highlight['kind'], string> = {
  // Monochromatic — all highlights share the same neutral surface; the icon
  // is the differentiator. Tax window gets a whisper-matcha tint to draw the eye.
  score_drop: 'border-zinc-200 bg-white text-zinc-700',
  news_alert: 'border-zinc-200 bg-zinc-50 text-zinc-700',
  tax_window: 'border-[var(--color-accent-2)] bg-[var(--color-accent-soft)] text-[color:var(--color-accent)]',
};

export function HighlightsStrip() {
  const [items, setItems] = useState<Highlight[]>([]);

  useEffect(() => {
    fetch(`${BACKEND}/api/advisor/highlights`)
      .then((r) => r.json())
      .then((j: { items: Highlight[] }) => setItems(j.items ?? []))
      .catch(() => setItems([]));
  }, []);

  if (!items.length) return null;

  return (
    <div className="mb-5 flex flex-wrap gap-2">
      {items.map((it, i) => {
        const Icon = ICON[it.kind];
        const inner = (
          <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border ${TINT[it.kind]}`}>
            <Icon size={12} />
            {it.text}
          </span>
        );
        return it.household_id ? (
          <Link key={i} href={`/plan/${it.household_id}`}>
            {inner}
          </Link>
        ) : (
          <span key={i}>{inner}</span>
        );
      })}
    </div>
  );
}
