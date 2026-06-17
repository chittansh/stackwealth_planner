'use client';

import { BarChart3, Table, Activity, Share, Download, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { Dropdown } from '@/components/ui/Dropdown';
import { ThemeToggle } from './ThemeToggle';
import { QuickAddMenu } from './QuickAddMenu';
import { fetchPlan, planSet } from '@/lib/api';
import { firePlanChanged } from '@/lib/prompt';

const VIEWS = [
  { value: 'net-worth', label: 'Net Worth' },
  { value: 'cash-flow', label: 'Cash Flow' },
  { value: 'investments', label: 'Investments' },
  { value: 'risk', label: 'Risk & Planning' },
  { value: 'allocation', label: 'Allocation' },
  { value: 'goals', label: 'Goals' },
  { value: 'insurance', label: 'Insurance' },
  { value: 'tax', label: 'Tax' },
  { value: 'debt', label: 'Debt Paydown' },
  { value: 'retirement', label: 'Retirement Glide' },
] as const;

const HORIZONS = [
  { value: 10, label: '10 years' },
  { value: 20, label: '20 years' },
  { value: 30, label: '30 years' },
  { value: 45, label: '45 years' },
  { value: 60, label: '60 years' },
] as const;

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

  const onHorizonChange = useCallback(
    async (v: number) => {
      setParam('horizon', v);
      // Push to the server so the cashflow + headline + chart all recompute.
      try {
        await planSet(householdId, 'computed.horizon_years', v);
        firePlanChanged();
      } catch {
        /* swallow — UI will stay on previous projection */
      }
    },
    [householdId, setParam],
  );

  const downloadReport = useCallback(() => {
    const url = `${process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000'}/api/report/${householdId}/pdf`;
    window.open(url, '_blank');
  }, [householdId]);

  const onShare = useCallback(async () => {
    const url = window.location.href;
    try {
      await navigator.clipboard.writeText(url);
      window.dispatchEvent(
        new CustomEvent('sw:toast', { detail: { text: 'Link copied to clipboard' } }),
      );
    } catch {
      /* clipboard blocked — silent */
    }
  }, []);

  const runMonteCarlo = useCallback(() => {
    // Surface live in the chat so the user can see the agent kick off the run.
    window.dispatchEvent(
      new CustomEvent('sw:chat-prompt', {
        detail: { prompt: 'Run a Monte Carlo simulation and tell me the P10/P50/P90 freedom age.' },
      }),
    );
  }, []);

  const [clientName, setClientName] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchPlan(householdId)
      .then((p) => !cancelled && setClientName(p.personal_details.full_name ?? null))
      .catch(() => undefined);
    const id = setInterval(() => {
      fetchPlan(householdId)
        .then((p) => !cancelled && setClientName(p.personal_details.full_name ?? null))
        .catch(() => undefined);
    }, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [householdId]);

  return (
    <header className="h-14 px-4 flex items-center gap-2 border-b border-zinc-200 bg-white">
      <Link
        href="/advisor/clients"
        className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 px-2 h-8 rounded-md hover:bg-zinc-50"
        title="Back to clients"
      >
        <ArrowLeft size={13} />
        <span className="hidden md:inline">Clients</span>
      </Link>
      <span className="text-zinc-300">/</span>
      <span className="text-sm text-zinc-800 max-w-[180px] truncate" title={clientName ?? householdId}>
        {clientName ?? <span className="text-zinc-400 font-mono">{householdId}</span>}
      </span>
      <span className="text-zinc-200 mx-1">·</span>
      <Dropdown
        value={view}
        options={VIEWS as unknown as { value: string; label: string }[]}
        onChange={(v) => setParam('view', v)}
        width={180}
      />
      <Dropdown
        value={horizon}
        options={HORIZONS as unknown as { value: number; label: string }[]}
        onChange={(v) => void onHorizonChange(Number(v))}
        width={140}
      />

      {/* Segmented chart/table/MC toggles */}
      <div className="ml-1 flex items-center rounded-md border border-zinc-200 overflow-hidden">
        <SegBtn
          active={view === 'net-worth'}
          title="Chart view"
          onClick={() => setParam('view', 'net-worth')}
        >
          <BarChart3 size={14} />
        </SegBtn>
        <SegBtn
          active={view === 'cash-flow'}
          title="Table view"
          onClick={() => setParam('view', 'cash-flow')}
        >
          <Table size={14} />
        </SegBtn>
        <SegBtn title="Run Monte Carlo simulation" onClick={runMonteCarlo}>
          <Activity size={14} />
        </SegBtn>
      </div>

      <QuickAddMenu householdId={householdId} />

      <div className="ml-auto flex items-center gap-2">
        <ThemeToggle />
        <button
          onClick={downloadReport}
          className="inline-flex items-center gap-1.5 text-xs px-2.5 h-8 rounded-md border border-zinc-200 hover:bg-zinc-50 text-zinc-700"
          title="Open print-styled report"
        >
          <Download size={13} /> Report
        </button>
        <button
          onClick={onShare}
          className="inline-flex items-center gap-1.5 text-xs px-2.5 h-8 rounded-md border border-zinc-200 hover:bg-zinc-50 text-zinc-700"
          title="Copy link to this household"
        >
          <Share size={13} /> Share
        </button>
        <a
          href={`/plan/${householdId}`}
          className="w-8 h-8 rounded-full bg-zinc-100 grid place-items-center text-[11px] text-zinc-600 hover:bg-zinc-200"
          title={`Household: ${householdId}`}
        >
          {householdId.slice(0, 2).toUpperCase()}
        </a>
      </div>
    </header>
  );
}

function SegBtn({
  active,
  title,
  onClick,
  children,
}: {
  active?: boolean;
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`w-8 h-8 grid place-items-center text-zinc-500 hover:bg-zinc-50 ${
        active ? 'bg-zinc-100 text-zinc-900' : ''
      }`}
    >
      {children}
    </button>
  );
}
