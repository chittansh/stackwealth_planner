'use client';

import {
  Area,
  Bar,
  ComposedChart,
  Line,
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
  fa_opening?: number;
  financial_assets_closing?: number;
  major_withdrawals?: number;
  goal_withdrawal?: number;
  remarks?: string;
};

/**
 * Year-by-year cash flow, framed around the Open FA (financial-asset) pool.
 * Everything is positive — there are no below-zero bars. Each year's living
 * costs are funded by earned income (salary / business / rental / other) and,
 * once that tapers after retirement, by a draw from the accumulated Open FA.
 * The Open FA balance itself rides on a second axis as an always-positive area,
 * so the chart only ever shows a deficit if the asset pool itself runs dry
 * (it doesn't here). Reads `plan.computed.cfp.yoy_cashflow`.
 */
export function CashFlowChart({ plan }: { plan: PlanState | null }) {
  const rows =
    ((plan?.computed?.cfp as { yoy_cashflow?: YoyRow[] } | undefined)?.yoy_cashflow as YoyRow[] | undefined) ?? [];

  if (rows.length === 0) return null;

  const data = rows.map((r) => {
    const income = Math.round((r.income_employment ?? 0) + (r.income_business ?? 0) + (r.income_rental ?? 0) + (r.income_other ?? 0));
    const living = Math.round((r.expenses ?? 0) + (r.loan_repayment ?? 0));
    // Gap funded by drawing on the accumulated Open FA (chiefly post-retirement).
    const drawn = Math.max(0, living - income);
    return {
      year: r.year,
      salary: Math.round(r.income_employment ?? 0),
      business: Math.round(r.income_business ?? 0),
      rental: Math.round(r.income_rental ?? 0),
      other: Math.round(r.income_other ?? 0),
      drawn,
      living,
      // Open FA pool (financial assets) — always positive, on the right axis.
      openFa: Math.round(r.fa_opening ?? r.financial_assets_closing ?? 0),
    };
  });

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="mb-1">
        <h3 className="text-sm font-medium text-zinc-800">Cash flow, year by year</h3>
        <p className="text-[11px] text-zinc-500 mt-0.5">
          Bars (left axis) show how each year&apos;s living costs are funded — earned income, then a draw from the Open FA
          once income tapers after retirement. The shaded area (right axis) is the Open FA pool itself. Nothing goes
          negative unless the asset pool runs dry.
        </p>
      </div>
      <div className="w-full h-[340px]">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 10, right: 8, bottom: 8, left: 0 }}>
            <defs>
              <linearGradient id="cf-openfa" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#5f7d56" stopOpacity={0.22} />
                <stop offset="100%" stopColor="#5f7d56" stopOpacity={0.02} />
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
              yAxisId="flows"
              tickFormatter={(v: number) => formatINR(v, { compact: true }).replace('₹', '')}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: '#a1a1aa' }}
              width={56}
            />
            <YAxis
              yAxisId="fa"
              orientation="right"
              tickFormatter={(v: number) => formatINR(v, { compact: true }).replace('₹', '')}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: '#9cae8f' }}
              width={56}
            />
            <Tooltip
              formatter={(v: number, name: string) => [formatINR(v, { compact: true }), name]}
              contentStyle={{ borderRadius: 8, border: '1px solid #e4e4e7', fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="square" />
            {/* Open FA pool — right axis, behind the bars */}
            <Area
              yAxisId="fa"
              type="monotone"
              dataKey="openFa"
              name="Open FA (financial assets)"
              stroke="#5f7d56"
              strokeWidth={1.25}
              fill="url(#cf-openfa)"
              dot={false}
            />
            {/* Annual funding sources (all positive) */}
            <Bar yAxisId="flows" dataKey="salary" name="Salary" stackId="cf" fill="#5f7d56" />
            <Bar yAxisId="flows" dataKey="business" name="Business" stackId="cf" fill="#7e9aa1" />
            <Bar yAxisId="flows" dataKey="rental" name="Rental" stackId="cf" fill="#9e8fb0" />
            <Bar yAxisId="flows" dataKey="other" name="Other" stackId="cf" fill="#c4a878" />
            <Bar yAxisId="flows" dataKey="drawn" name="Drawn from Open FA" stackId="cf" fill="#8bb0a0" />
            {/* Living costs the funding must cover (positive line) */}
            <Line yAxisId="flows" type="monotone" dataKey="living" name="Living costs (expenses + EMI)" stroke="#b06a6a" strokeWidth={1.75} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
