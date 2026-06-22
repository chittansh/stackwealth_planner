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
    const income = Math.round((r.income_employment ?? 0) + (r.income_business ?? 0) + (r.income_rental ?? 0) + (r.income_other ?? 0));
    const out = Math.round((r.expenses ?? 0) + (r.loan_repayment ?? 0));
    const operating = income - out;
    // When earned income can't cover the year's living costs (chiefly after
    // retirement, when salary/business stop), the gap is met by drawing on the
    // accumulated financial assets (Open FA) — the corpus the plan built for
    // exactly this. Surface that draw as an inflow so the picture is honest and
    // the net line never dives below zero "for no reason".
    const drawn = Math.max(0, -operating);
    return {
      year: r.year,
      salary: Math.round(r.income_employment ?? 0),
      business: Math.round(r.income_business ?? 0),
      rental: Math.round(r.income_rental ?? 0),
      other: Math.round(r.income_other ?? 0),
      drawn,
      // Outflows as negatives so they stack downward from the zero line. Goal
      // spends are excluded — they're one-off Open FA draws, not annual income.
      expenses: -Math.round(r.expenses ?? 0),
      emi: -Math.round(r.loan_repayment ?? 0),
      // Net line: surplus to invest while earning; 0 once the corpus covers costs.
      net: Math.max(0, operating),
    };
  });

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="mb-1">
        <h3 className="text-sm font-medium text-zinc-800">Cash flow, year by year</h3>
        <p className="text-[11px] text-zinc-500 mt-0.5">
          Inflows above the line by source; living expenses and EMI below. After retirement, earned income tapers and the
          gap is drawn from accumulated assets (Open FA) — shown as its own band, so net cash stays covered. Goal spends are
          asset-funded too (see the table and net-worth-by-asset chart).
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
            <Bar dataKey="drawn" name="Drawn from assets" stackId="cf" fill="#8bb0a0" />
            {/* Outflows (stack down) — goal spends excluded (asset-funded) */}
            <Bar dataKey="expenses" name="Living expenses" stackId="cf" fill="#d98c8c" />
            <Bar dataKey="emi" name="EMI" stackId="cf" fill="#c97b7b" />
            {/* Net cash line — surplus to invest while earning, 0 once corpus-funded */}
            <Line
              type="monotone"
              dataKey="net"
              name="Net surplus to invest"
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
