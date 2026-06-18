'use client';

import { useState } from 'react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

type Mode = 'cashflow' | 'assets';

/**
 * Year-by-year projection table with two complementary views:
 *
 *  • cashflow — what flows IN and OUT each year (income, expenses,
 *    goal spends, taxes) and the resulting net worth.
 *
 *  • assets — END-OF-YEAR snapshot of each asset class (cash,
 *    investments, real estate, gold) plus total net worth. Shows
 *    how the portfolio composition shifts as SIPs accumulate, goals
 *    fire, and the household moves through retirement.
 *
 * Each row also carries a tiny stacked bar visualising that year's
 * net-worth composition by class — at-a-glance "where my wealth is"
 * for any year on the horizon.
 */
export function CashFlowTable({ plan }: { plan: PlanState | null }) {
  const [mode, setMode] = useState<Mode>('assets');
  const rows = plan?.computed.cash_flow_table ?? [];

  if (!rows.length) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Cash flow appears once income and expenses are set. Drop a statement or paste your numbers.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-zinc-200 overflow-hidden bg-white">
      {/* ── Header / toggle ──────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
        <div>
          <h3 className="text-sm font-medium text-zinc-800">Year-by-year projection</h3>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            {mode === 'assets'
              ? 'End-of-year breakdown by asset class.'
              : 'Inflows and outflows per year.'}
          </p>
        </div>
        <div className="inline-flex items-center rounded-lg border border-zinc-200 p-0.5 text-[11px]">
          <ModeButton active={mode === 'assets'} onClick={() => setMode('assets')}>
            Assets
          </ModeButton>
          <ModeButton active={mode === 'cashflow'} onClick={() => setMode('cashflow')}>
            Cashflow
          </ModeButton>
        </div>
      </div>

      {/* ── Table ────────────────────────────────────────────────── */}
      <div className="max-h-[520px] overflow-auto">
        {mode === 'assets' ? <AssetsTable rows={rows} /> : <CashflowTableInner rows={rows} />}
      </div>
    </div>
  );
}

/* ── Asset-class view ──────────────────────────────────────────────── */

type Row = NonNullable<PlanState['computed']['cash_flow_table']>[number];

function AssetsTable({ rows }: { rows: Row[] }) {
  return (
    <table className="min-w-full text-xs tabular-nums">
      <thead className="sticky top-0 bg-zinc-50 text-zinc-500 z-10">
        <tr>
          <Th>Year</Th>
          <Th right>Age</Th>
          <Th right>Cash</Th>
          <Th right>Investments</Th>
          <Th right>Real estate</Th>
          <Th right>Gold</Th>
          <Th right>Goal spend</Th>
          <Th right>Net worth</Th>
          <Th>Composition</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const liquid = r.liquid ?? 0;
          const portfolio = r.portfolio ?? r.assets ?? 0;
          const realEstate = r.real_estate ?? 0;
          const gold = r.gold ?? 0;
          const goalOut = r.goal_outflow ?? 0;
          const total = r.total_net_worth || liquid + portfolio + realEstate + gold;
          return (
            <tr key={i} className="border-b border-zinc-100 hover:bg-zinc-50/60">
              <Td>{r.year}</Td>
              <Td right>{r.age}</Td>
              <Td right>{fmt(liquid)}</Td>
              <Td right>{fmt(portfolio)}</Td>
              <Td right>{fmt(realEstate)}</Td>
              <Td right>{fmt(gold)}</Td>
              <Td right tone={goalOut > 0 ? 'warn' : undefined}>
                {goalOut > 0 ? `−${fmt(goalOut)}` : '—'}
              </Td>
              <Td right strong>
                {fmt(total)}
              </Td>
              <td className="px-3 py-1.5 w-[140px]">
                <CompositionBar
                  liquid={liquid}
                  portfolio={portfolio}
                  realEstate={realEstate}
                  gold={gold}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ── Inflow / outflow view (the old table, condensed) ──────────────── */

function CashflowTableInner({ rows }: { rows: Row[] }) {
  return (
    <table className="min-w-full text-xs tabular-nums">
      <thead className="sticky top-0 bg-zinc-50 text-zinc-500 z-10">
        <tr>
          <Th>Year</Th>
          <Th right>Age</Th>
          <Th right>Income</Th>
          <Th right>Expenses</Th>
          <Th right>Taxes</Th>
          <Th right>Goal spend</Th>
          <Th right>Net surplus</Th>
          <Th right>Net worth</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const surplus = r.income - r.expenses - r.taxes - (r.goal_outflow ?? 0);
          return (
            <tr key={i} className="border-b border-zinc-100 hover:bg-zinc-50/60">
              <Td>{r.year}</Td>
              <Td right>{r.age}</Td>
              <Td right tone={r.income > 0 ? 'good' : undefined}>{r.income > 0 ? fmt(r.income) : '—'}</Td>
              <Td right>{fmt(r.expenses)}</Td>
              <Td right>{r.taxes > 0 ? fmt(r.taxes) : '—'}</Td>
              <Td right tone={(r.goal_outflow ?? 0) > 0 ? 'warn' : undefined}>
                {(r.goal_outflow ?? 0) > 0 ? `−${fmt(r.goal_outflow ?? 0)}` : '—'}
              </Td>
              <Td right tone={surplus >= 0 ? 'good' : 'bad'}>
                {surplus >= 0 ? fmt(surplus) : `−${fmt(-surplus)}`}
              </Td>
              <Td right strong>{fmt(r.total_net_worth)}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ── Bits ──────────────────────────────────────────────────────────── */

function fmt(n: number): string {
  return formatINR(n, { compact: true });
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th
      className={`px-3 py-2 font-medium border-b border-zinc-200 text-[10px] uppercase tracking-wide ${
        right ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  right,
  strong,
  tone,
}: {
  children: React.ReactNode;
  right?: boolean;
  strong?: boolean;
  tone?: 'good' | 'warn' | 'bad';
}) {
  const cls =
    tone === 'good'
      ? 'text-[color:var(--color-accent,#5f7d56)]'
      : tone === 'warn'
      ? 'text-amber-700'
      : tone === 'bad'
      ? 'text-rose-700'
      : strong
      ? 'text-zinc-900 font-medium'
      : 'text-zinc-700';
  return (
    <td className={`px-3 py-1.5 whitespace-nowrap ${right ? 'text-right' : 'text-left'} ${cls}`}>
      {children}
    </td>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded-md text-[11px] font-medium transition-colors ${
        active ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-500 hover:text-zinc-800'
      }`}
    >
      {children}
    </button>
  );
}

function CompositionBar({
  liquid,
  portfolio,
  realEstate,
  gold,
}: {
  liquid: number;
  portfolio: number;
  realEstate: number;
  gold: number;
}) {
  const total = liquid + portfolio + realEstate + gold;
  if (total <= 0) return <span className="text-zinc-300 text-[10px]">—</span>;
  // Same accents used on the Investments page so the visual language matches.
  const segs = [
    { v: liquid, color: '#a1a1aa', label: 'Cash' },
    { v: portfolio, color: 'var(--color-accent, #5f7d56)', label: 'Investments' },
    { v: realEstate, color: '#c4a878', label: 'Real estate' },
    { v: gold, color: '#d4b878', label: 'Gold' },
  ].filter((s) => s.v > 0);
  return (
    <div
      className="flex h-2 rounded-full overflow-hidden bg-zinc-100"
      title={segs.map((s) => `${s.label}: ${formatINR(s.v, { compact: true })}`).join(' · ')}
    >
      {segs.map((s, i) => (
        <div key={i} style={{ width: `${(s.v / total) * 100}%`, backgroundColor: s.color }} />
      ))}
    </div>
  );
}
