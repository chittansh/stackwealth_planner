'use client';

import { ChevronDown, BarChart3, Table, Sparkles, Plus, Search, Share, User } from 'lucide-react';
import { useState } from 'react';

const VIEWS = ['Net Worth', 'Cash Flow', 'Allocation', 'Goals', 'Insurance', 'Tax'] as const;
const HORIZONS = ['10 years', '20 years', '30 years', '45 years'] as const;

export function TopBar({ householdId: _ }: { householdId: string }) {
  const [view, setView] = useState<(typeof VIEWS)[number]>('Net Worth');
  const [horizon, setHorizon] = useState<(typeof HORIZONS)[number]>('45 years');

  return (
    <header className="h-14 px-6 flex items-center gap-3 border-b border-zinc-200">
      <Pill>
        <select
          value={view}
          onChange={(e) => setView(e.target.value as typeof view)}
          className="bg-transparent outline-none pr-1 cursor-pointer"
        >
          {VIEWS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <ChevronDown size={14} className="opacity-60" />
      </Pill>
      <Pill>
        <select
          value={horizon}
          onChange={(e) => setHorizon(e.target.value as typeof horizon)}
          className="bg-transparent outline-none pr-1 cursor-pointer"
        >
          {HORIZONS.map((h) => (
            <option key={h} value={h}>
              {h}
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
