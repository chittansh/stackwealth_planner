'use client';

import { ChevronDown, BarChart3, Table, Sparkles, Plus, Search, Share, User, Download } from 'lucide-react';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { useCallback } from 'react';

const VIEWS = [
  { id: 'net-worth', label: 'Net Worth' },
  { id: 'cash-flow', label: 'Cash Flow' },
  { id: 'allocation', label: 'Allocation' },
  { id: 'goals', label: 'Goals' },
  { id: 'insurance', label: 'Insurance' },
  { id: 'tax', label: 'Tax' },
] as const;

const HORIZONS = [10, 20, 30, 45] as const;

export function TopBar({
  householdId,
  view,
  horizon,
}: {
  householdId: string;
  view: string;
  horizon: number;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const setParam = useCallback(
    (k: string, v: string | number) => {
      const u = new URLSearchParams(sp.toString());
      u.set(k, String(v));
      router.replace(`${pathname}?${u.toString()}`, { scroll: false });
    },
    [router, pathname, sp],
  );

  const downloadReport = useCallback(() => {
    const url = `${process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000'}/api/report/${householdId}/pdf`;
    window.open(url, '_blank');
  }, [householdId]);

  return (
    <header className="h-14 px-6 flex items-center gap-3 border-b border-zinc-200 bg-white">
      <Pill>
        <select
          value={view}
          onChange={(e) => setParam('view', e.target.value)}
          className="appearance-none bg-transparent outline-none pr-1 cursor-pointer"
        >
          {VIEWS.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label}
            </option>
          ))}
        </select>
        <ChevronDown size={14} className="opacity-60" />
      </Pill>

      <Pill>
        <select
          value={horizon}
          onChange={(e) => setParam('horizon', e.target.value)}
          className="appearance-none bg-transparent outline-none pr-1 cursor-pointer"
        >
          {HORIZONS.map((h) => (
            <option key={h} value={h}>
              {h} years
            </option>
          ))}
        </select>
        <ChevronDown size={14} className="opacity-60" />
      </Pill>

      <div className="ml-2 flex items-center rounded-lg border border-zinc-200 overflow-hidden">
        <IconBtn aria-label="chart"><BarChart3 size={14} /></IconBtn>
        <IconBtn aria-label="table"><Table size={14} /></IconBtn>
        <IconBtn aria-label="annotated"><Sparkles size={14} /></IconBtn>
      </div>

      <button className="ml-2 w-8 h-8 rounded-md border border-zinc-200 grid place-items-center hover:bg-zinc-50">
        <Plus size={14} />
      </button>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={downloadReport}
          className="inline-flex items-center gap-1.5 text-xs px-2.5 h-8 rounded-md border border-zinc-200 hover:bg-zinc-50"
          title="Download plan PDF"
        >
          <Download size={14} /> Report
        </button>
        <IconBtn aria-label="search"><Search size={16} /></IconBtn>
        <IconBtn aria-label="share"><Share size={16} /></IconBtn>
        <div className="w-8 h-8 rounded-full bg-zinc-200 grid place-items-center text-xs">
          <User size={14} />
        </div>
      </div>
    </header>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <div className="inline-flex items-center gap-1 px-2.5 h-8 rounded-md border border-zinc-200 text-sm hover:bg-zinc-50">
      {children}
    </div>
  );
}

function IconBtn({ children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...rest} className="w-8 h-8 grid place-items-center hover:bg-zinc-50 text-zinc-500">
      {children}
    </button>
  );
}
