'use client';

import { useEffect, useState } from 'react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import type { DebtPaydownOutput, PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

const LOAN_LABEL: Record<string, string> = {
  home_loan: 'Home loan',
  car_loan: 'Car loan',
  personal_loan: 'Personal loan',
  credit_card_dues: 'Credit-card dues',
};

export function DebtPaydownView({
  householdId,
  plan,
}: {
  householdId: string;
  plan: PlanState | null;
}) {
  const cached = plan?.computed.debt_paydown;
  const [data, setData] = useState<DebtPaydownOutput | null>(cached ?? null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (cached) setData(cached);
  }, [cached]);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`${BACKEND}/api/skill/debt/${householdId}`, { method: 'POST' });
      const j = (await r.json()) as DebtPaydownOutput | { error: string };
      if ('error' in j) setErr(j.error);
      else setData(j);
    } finally {
      setBusy(false);
    }
  };

  // Empty state: either no loans on the plan, or the skill hasn't been run yet.
  const hasLoans = data?.schedules.length ? data.schedules.length > 0 : false;
  if (!data || !hasLoans) {
    const hasAnyLoan = !!(
      plan?.loans_liabilities.home_loan?.outstanding_amount ||
      plan?.loans_liabilities.car_loan?.outstanding_amount ||
      plan?.loans_liabilities.personal_loan?.outstanding_amount ||
      plan?.loans_liabilities.credit_card_dues?.outstanding_amount
    );
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center flex flex-col items-center gap-2">
        {hasAnyLoan ? (
          <>
            <p>Run the debt paydown schedule to see when each loan ends + total interest.</p>
            <button
              onClick={run}
              disabled={busy}
              className="text-xs px-3 py-1.5 rounded-md bg-zinc-900 text-white disabled:opacity-50"
            >
              {busy ? 'Computing…' : 'Run paydown schedule'}
            </button>
          </>
        ) : (
          <p>No loans on the plan. Tell the planner about any active loans (home, car, personal, credit card).</p>
        )}
        {err && <p className="text-xs text-zinc-500">{err}</p>}
      </div>
    );
  }

  // Stacked aggregate chart: opening balance per year, broken down by loan.
  const yearKeys = data.schedules.map((s) => s.loan_type);
  const balancesByYear: Record<number, Record<string, number>> = {};
  data.schedules.forEach((s) => {
    s.rows.forEach((r) => {
      balancesByYear[r.year] = balancesByYear[r.year] || { year: r.year };
      balancesByYear[r.year][s.loan_type] = r.closing_balance;
    });
  });
  const chartData = Object.values(balancesByYear).sort((a, b) => (a.year as number) - (b.year as number));

  const palette = ['#52525b', '#87a17e', '#a18a7e', '#9e7ea1'];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="Total outstanding" value={formatINR(data.total_outstanding_today, { compact: true })} />
        <Stat label="Monthly EMI total" value={formatINR(data.total_emi_monthly, { compact: true })} />
        <Stat label="Interest over term" value={formatINR(data.total_interest_over_term, { compact: true })} />
        <Stat label="Debt-free year" value={String(data.last_emi_year)} />
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">Outstanding balance by year</h3>
        <div className="w-full h-[240px]">
          <ResponsiveContainer>
            <AreaChart data={chartData} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
              <defs>
                {yearKeys.map((k, i) => (
                  <linearGradient key={k} id={`grad-debt-${i}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={palette[i % palette.length]} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={palette[i % palette.length]} stopOpacity={0.03} />
                  </linearGradient>
                ))}
              </defs>
              <XAxis dataKey="year" tickLine={false} axisLine={false} interval="preserveStartEnd" tick={{ fontSize: 11, fill: '#a1a1aa' }} />
              <YAxis
                tickFormatter={(v: number) => formatINR(v, { compact: true }).replace('₹', '')}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: '#a1a1aa' }}
                width={64}
              />
              <Tooltip
                formatter={(v: number) => formatINR(v, { compact: true })}
                contentStyle={{ borderRadius: 8, border: '1px solid #e4e4e7', fontSize: 12 }}
              />
              {yearKeys.map((k, i) => (
                <Area
                  key={k}
                  type="monotone"
                  dataKey={k}
                  name={LOAN_LABEL[k] ?? k}
                  stackId="1"
                  stroke={palette[i % palette.length]}
                  strokeWidth={1.5}
                  fill={`url(#grad-debt-${i})`}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">Per-loan schedule</h3>
        <table className="w-full text-xs">
          <thead className="text-zinc-500">
            <tr className="text-left border-b border-zinc-100">
              <th className="py-1.5">Loan</th>
              <th className="text-right">Outstanding</th>
              <th className="text-right">EMI</th>
              <th className="text-right">Rate</th>
              <th className="text-right">Tenure left</th>
              <th className="text-right">Total interest</th>
              <th className="text-right">Ends</th>
            </tr>
          </thead>
          <tbody>
            {data.schedules.map((s) => (
              <tr key={s.loan_type} className="border-b border-zinc-100 last:border-0">
                <td className="py-1.5 text-zinc-800">{LOAN_LABEL[s.loan_type] ?? s.loan_type}</td>
                <td className="text-right tabular-nums">{formatINR(s.outstanding_amount, { compact: true })}</td>
                <td className="text-right tabular-nums">{formatINR(s.emi, { compact: true })}</td>
                <td className="text-right tabular-nums">{s.interest_rate.toFixed(1)}%</td>
                <td className="text-right tabular-nums">{s.tenure_left_years.toFixed(1)} y</td>
                <td className="text-right tabular-nums">{formatINR(s.total_interest_paid, { compact: true })}</td>
                <td className="text-right tabular-nums">{s.final_year}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.note && <p className="mt-3 text-[11px] text-zinc-400">{data.note}</p>}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-zinc-400">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-zinc-800 mt-0.5">{value}</div>
    </div>
  );
}
