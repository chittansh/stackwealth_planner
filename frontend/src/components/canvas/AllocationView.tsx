'use client';

import { Pie, PieChart, ResponsiveContainer, Cell, Tooltip } from 'recharts';
import type { PlanState } from '@/types/plan-state';
import { ChevronRight } from 'lucide-react';
import { useState } from 'react';

const COLORS_STRATEGIC = ['#6b8ee5', '#7dd3fc', '#fbbf24', '#a3a3a3'];
const COLORS_RECOMMENDED = ['#a189d6', '#67e8f9', '#facc15', '#9ca3af'];

export function AllocationView({ plan }: { plan: PlanState | null }) {
  const a = plan?.computed.allocation;
  const [showWhy, setShowWhy] = useState(false);

  if (!a) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Allocation appears once a risk profile is set. Tell me how you’d react to a 30% drawdown.
      </div>
    );
  }

  const strategicData = [
    { name: 'Equity', value: a.strategic_allocation.equity },
    { name: 'Debt', value: a.strategic_allocation.debt },
    { name: 'Gold', value: a.strategic_allocation.gold },
    { name: 'Cash', value: a.strategic_allocation.cash },
  ];
  const recommendedData = [
    { name: 'Equity', value: a.recommended_allocation.equity },
    { name: 'Debt', value: a.recommended_allocation.debt },
    { name: 'Gold', value: a.recommended_allocation.gold },
    { name: 'Cash', value: a.recommended_allocation.cash },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card title="Strategic" subtitle={`${a.investor_risk_band} anchor`}>
        <Donut data={strategicData} colors={COLORS_STRATEGIC} />
        <Legend data={strategicData} colors={COLORS_STRATEGIC} />
      </Card>
      <Card
        title="Recommended"
        subtitle={`${a.tactical_regime_label} (score ${a.tactical_regime_score})`}
        action={
          <button
            onClick={() => setShowWhy((v) => !v)}
            className="text-xs text-zinc-500 inline-flex items-center gap-1 hover:text-zinc-800"
          >
            why <ChevronRight size={12} className={showWhy ? 'rotate-90 transition' : 'transition'} />
          </button>
        }
      >
        <Donut data={recommendedData} colors={COLORS_RECOMMENDED} />
        <Legend data={recommendedData} colors={COLORS_RECOMMENDED} />
        {showWhy && (
          <div className="mt-3 border-t border-zinc-100 pt-3 text-xs text-zinc-600 space-y-1">
            {Object.entries(a.signal_breakdown).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="capitalize">{k}</span>
                <span className="tabular-nums">
                  {v.score >= 0 ? `+${v.score}` : v.score} · {v.reason}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-3 gap-4">
        <SmallCard label="Equity Split (Recommended)">
          <div className="flex gap-3 text-sm">
            <span>L {a.recommended_equity_split.large}%</span>
            <span>M {a.recommended_equity_split.mid}%</span>
            <span>S {a.recommended_equity_split.small}%</span>
          </div>
        </SmallCard>
        <SmallCard label="Debt Duration">
          <span className="text-sm capitalize">{a.debt_duration_stance}</span>
        </SmallCard>
        <SmallCard label="Warnings">
          <ul className="text-xs text-amber-600 space-y-0.5">
            {(a.warnings.length ? a.warnings : ['—']).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </SmallCard>
      </div>
    </div>
  );
}

function Card({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-2">
        <div>
          <h3 className="text-sm font-medium text-zinc-700">{title}</h3>
          <p className="text-xs text-zinc-400">{subtitle}</p>
        </div>
        {action}
      </header>
      {children}
    </div>
  );
}

function SmallCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-3">
      <div className="text-[11px] uppercase tracking-wide text-zinc-400 mb-1">{label}</div>
      {children}
    </div>
  );
}

function Donut({ data, colors }: { data: { name: string; value: number }[]; colors: string[] }) {
  return (
    <div className="h-[180px]">
      <ResponsiveContainer>
        <PieChart>
          <Tooltip formatter={(v: number) => `${v}%`} />
          <Pie data={data} dataKey="value" innerRadius={50} outerRadius={70} paddingAngle={2}>
            {data.map((_, i) => (
              <Cell key={i} fill={colors[i % colors.length]} stroke="none" />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function Legend({ data, colors }: { data: { name: string; value: number }[]; colors: string[] }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2 text-xs">
      {data.map((d, i) => (
        <div key={d.name} className="flex items-center justify-between">
          <span className="inline-flex items-center gap-1.5 text-zinc-600">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: colors[i] }} />
            {d.name}
          </span>
          <span className="tabular-nums text-zinc-800">{d.value}%</span>
        </div>
      ))}
    </div>
  );
}
