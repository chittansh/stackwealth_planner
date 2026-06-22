'use client';

import {
  Bar,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from 'recharts';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

type YoyRow = {
  year: number;
  age: number;
  income_employment?: number;
  income_business?: number;
  income_rental?: number;
  income_other?: number;
  expenses?: number;
  loan_repayment?: number;
  surplus?: number;
  major_withdrawals?: number;
  goal_withdrawal?: number;
  remarks?: string;
};

/**
 * Granular year-by-year cash flow. Income sources stack ABOVE the zero line
 * (salary / business / rental / other); outflows stack BELOW it (living
 * expenses, EMI, goal withdrawals). A line traces the net annual surplus so the
 * advisor sees, per year, exactly what comes in, what goes out, and what is left
 * to invest. Reads `plan.computed.cfp.yoy_cashflow`.
 */
export function CashFlowChart({ plan }: { plan: PlanState | null }) {
  const rows =
    ((plan?.computed?.cfp as { yoy_cashflow?: YoyRow[] } | undefined)?.yoy_cashflow as YoyRow[] | undefined) ?? [];

  if (rows.length === 0) return null;

  const data = rows.map((r) => {
    const withdrawal = Math.abs(r.major_withdrawals ?? r.goal_withdrawal ?? 0);
    return {
      year: r.year,
      salary: Math.round(r.income_employment ?? 0),
      business: Math.round(r.income_business ?? 0),
      rental: Math.round(r.income_rental ?? 0),
      other: Math.round(r.income_other ?? 0),
      // Outflows as negatives so they stack downward from the zero line.
      expenses: -Math.round(r.expenses ?? 0),
      emi: -Math.round(r.loan_repayment ?? 0),
      goals: -Math.round(withdrawal),
      surplus: Math.round(r.surplus ?? 0),
    };
  });

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="mb-1">
        <h3 className="text-sm font-medium text-zinc-800">Cash flow, year by year</h3>
        <p className="text-[11px] text-zinc-500 mt-0.5">
          Inflows above the line by source; outflows below (expenses, EMI, goal spends). The line is net surplus.
        </p>
      </div>
      <div className="w-full h-[320px]">
        <ResponsiveContainer>
          <ComposedChart data={data} stackOffset="sign" margin={{ top: 10, right: 24, bottom: 8, left: 0 }}>
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
              formatter={(v: number, name: string) => [formatINR(Math.abs(v), { compact: true }), name]}
              contentStyle={{ borderRadius: 8, border: '1px solid #e4e4e7', fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="square" />
            <ReferenceLine y={0} stroke="#d4d4d8" />
            {/* Inflows (stack up) */}
            <Bar dataKey="salary" name="Salary" stackId="cf" fill="#5f7d56" />
            <Bar dataKey="business" name="Business" stackId="cf" fill="#7e9aa1" />
            <Bar dataKey="rental" name="Rental" stackId="cf" fill="#9e8fb0" />
            <Bar dataKey="other" name="Other" stackId="cf" fill="#c4a878" />
            {/* Outflows (stack down) */}
            <Bar dataKey="expenses" name="Living expenses" stackId="cf" fill="#d98c8c" />
            <Bar dataKey="emi" name="EMI" stackId="cf" fill="#c97b7b" />
            <Bar dataKey="goals" name="Goal spends" stackId="cf" fill="#a85b5b" />
            {/* Net surplus line */}
            <Line
              type="monotone"
              dataKey="surplus"
              name="Net surplus"
              stroke="#27272a"
              strokeWidth={1.75}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
