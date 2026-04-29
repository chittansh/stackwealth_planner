'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function CurrentNetWorthCard({ plan }: { plan: PlanState }) {
  const cash = plan.liquid_capital.savings_account_balance ?? 0;
  const investments = plan.computed.net_worth.assets_total - cash;
  const debts = plan.computed.net_worth.debts_total;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Current net worth</h3>
        <button className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:bg-zinc-50">
          <Plus size={14} />
        </button>
      </header>
      <Section label="Assets">
        <Row label="Cash" value={cash} />
        <Row label="Investments" value={investments} />
      </Section>
      <Section label="Debts" className="mt-3">
        <Row label="Total" value={-Math.abs(debts)} />
      </Section>
    </div>
  );
}

function Section({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="text-xs uppercase tracking-wide text-zinc-400 mb-1">{label}</div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-zinc-700">{label}</span>
      <span className="text-zinc-900 tabular-nums">{formatINR(value, { compact: true })}</span>
    </div>
  );
}
