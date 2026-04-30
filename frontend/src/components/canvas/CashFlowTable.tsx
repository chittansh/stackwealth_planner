'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

const COLS = [
  { id: 'year', label: 'Year', align: 'left' as const },
  { id: 'age', label: 'Age', align: 'right' as const },
  { id: 'assets', label: 'Assets', align: 'right' as const },
  { id: 'income', label: 'Income', align: 'right' as const },
  { id: 'expenses', label: 'Expenses', align: 'right' as const },
  { id: 'taxes', label: 'Taxes', align: 'right' as const },
  { id: 'retirement_contributions', label: 'Retirement', align: 'right' as const },
  { id: 'other', label: 'Other', align: 'right' as const },
  { id: 'total_net_worth', label: 'Total NW', align: 'right' as const },
];

export function CashFlowTable({ plan }: { plan: PlanState | null }) {
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
      <div className="max-h-[420px] overflow-auto">
        <table className="min-w-full text-sm tabular-nums">
          <thead className="sticky top-0 bg-zinc-50 text-zinc-500 z-10">
            <tr>
              {COLS.map((c) => (
                <th
                  key={c.id}
                  className={`px-3 py-2 font-medium border-b border-zinc-200 text-xs uppercase tracking-wide ${
                    c.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-zinc-100 hover:bg-zinc-50/60">
                {COLS.map((c) => {
                  const v = (r as unknown as Record<string, number>)[c.id];
                  const isMoney = c.id !== 'year' && c.id !== 'age';
                  return (
                    <td
                      key={c.id}
                      className={`px-3 py-1.5 ${c.align === 'right' ? 'text-right' : 'text-left'} ${
                        c.id === 'total_net_worth' ? 'font-medium text-zinc-900' : 'text-zinc-700'
                      }`}
                    >
                      {isMoney ? formatINR(Number(v ?? 0), { compact: true }) : v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
