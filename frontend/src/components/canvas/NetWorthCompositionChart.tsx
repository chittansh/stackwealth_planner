'use client';

import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip, Legend } from 'recharts';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

type YoyRow = {
  year: number;
  financial_assets_closing?: number;
  non_financial_assets_closing?: number;
  net_worth?: number;
};

/**
 * Net worth decomposed into Financial assets (cash, MFs, equity, FD, EPF…) and
 * Hard assets (real estate + gold), stacked over the full horizon. Sits next to
 * the headline net-worth trajectory so the advisor can see WHAT the net worth is
 * made of, not just its total — and how the financial pool overtakes hard assets
 * as surplus compounds. Reads `plan.computed.cfp.yoy_cashflow`.
 */
export function NetWorthCompositionChart({ plan }: { plan: PlanState | null }) {
  const rows =
    ((plan?.computed?.cfp as { yoy_cashflow?: YoyRow[] } | undefined)?.yoy_cashflow as YoyRow[] | undefined) ?? [];

  if (rows.length === 0) return null;

  const data = rows.map((r) => ({
    year: r.year,
    financial: Math.max(0, Math.round(r.financial_assets_closing ?? 0)),
    hard: Math.max(0, Math.round(r.non_financial_assets_closing ?? 0)),
  }));

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="mb-1">
        <h3 className="text-sm font-medium text-zinc-800">Net worth by asset type</h3>
        <p className="text-[11px] text-zinc-500 mt-0.5">
          Financial assets (cash, funds, equity, FD, EPF) vs hard assets (real estate, gold), stacked to net worth.
        </p>
      </div>
      <div className="w-full h-[280px]">
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 10, right: 24, bottom: 8, left: 0 }}>
            <defs>
              <linearGradient id="grad-financial" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#5f7d56" stopOpacity={0.45} />
                <stop offset="100%" stopColor="#5f7d56" stopOpacity={0.08} />
              </linearGradient>
              <linearGradient id="grad-hard" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#c4a878" stopOpacity={0.5} />
                <stop offset="100%" stopColor="#c4a878" stopOpacity={0.1} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="year"
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              tick={{ fontSize: 11, fill: '#a1a1aa' }}
            />
            <YAxis
              tickFormatter={(v: number) => formatINR(v, { compact: true }).replace('₹', '')}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: '#a1a1aa' }}
              width={64}
            />
            <Tooltip
              formatter={(v: number, name: string) => [formatINR(v, { compact: true }), name]}
              contentStyle={{ borderRadius: 8, border: '1px solid #e4e4e7', fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="square" />
            <Area
              type="monotone"
              dataKey="hard"
              name="Hard assets"
              stackId="nw"
              stroke="#b3996a"
              strokeWidth={1.25}
              fill="url(#grad-hard)"
              dot={false}
            />
            <Area
              type="monotone"
              dataKey="financial"
              name="Financial assets"
              stackId="nw"
              stroke="#5f7d56"
              strokeWidth={1.25}
              fill="url(#grad-financial)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
