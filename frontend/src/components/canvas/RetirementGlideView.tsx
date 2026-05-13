'use client';

import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

/**
 * Retirement Glide — a dedicated view that zooms the net-worth trajectory on
 * the retirement transition: the years leading up to the user's retirement
 * age + the post-retirement drawdown. Existing cashflow data; new framing.
 *
 * Surfaces three things the headline chart hides:
 *  - Retirement-year net worth (the corpus they actually retire with)
 *  - Whether the corpus survives the post-retirement horizon
 *  - The "real" annual outflow in retirement years (income drops to ₹0)
 */
export function RetirementGlideView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const rows = plan.computed.cashflow?.rows ?? [];
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Run cashflow first — this view shows the asset trajectory through retirement.
      </div>
    );
  }

  const retireAge = plan.assumptions.persons[0]?.retirement_age ?? plan.personal_details.retirement_age_target ?? 60;
  const startAge = plan.freedom_score_inputs.age ?? rows[0].age;
  const retireYear = rows.find((r) => r.age >= retireAge)?.year ?? rows[rows.length - 1].year;

  // Show 5 years before retirement through end of horizon — focuses the chart
  // on the transition rather than the full 45-year span.
  const focusFrom = Math.max(rows[0].year, retireYear - 5);
  const focused = rows.filter((r) => r.year >= focusFrom);

  // Retirement-year corpus + terminal corpus.
  const retireRow = rows.find((r) => r.year === retireYear);
  const terminalRow = rows[rows.length - 1];
  const drawdownYears = terminalRow.age - retireAge;

  // Sanity check: did the corpus survive? It dies the year `assets` first
  // hits zero AFTER retirement. Surface for transparency.
  const exhaustionRow = rows.find((r) => r.age >= retireAge && r.assets <= 0);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="Current age" value={`${startAge}`} note={`retire at ${retireAge}`} />
        <Stat
          label={`Corpus at age ${retireAge}`}
          value={formatINR(retireRow?.total_net_worth ?? 0, { compact: true })}
          note={`year ${retireYear}`}
        />
        <Stat
          label={`Terminal (age ${terminalRow.age})`}
          value={formatINR(terminalRow.total_net_worth, { compact: true })}
          note={`${drawdownYears}y in retirement`}
        />
        <Stat
          label="Corpus exhausted?"
          value={exhaustionRow ? `Age ${exhaustionRow.age}` : 'No'}
          note={exhaustionRow ? `year ${exhaustionRow.year}` : `survives all ${drawdownYears}y`}
          accent={exhaustionRow ? 'bad' : 'good'}
        />
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">
          Asset trajectory through retirement
        </h3>
        <div className="w-full h-[280px]">
          <ResponsiveContainer>
            <AreaChart data={focused} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
              <defs>
                <linearGradient id="grad-glide" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#87a17e" stopOpacity={0.32} />
                  <stop offset="100%" stopColor="#87a17e" stopOpacity={0.03} />
                </linearGradient>
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
              <ReferenceLine
                x={retireYear}
                stroke="#52525b"
                strokeDasharray="4 4"
                label={{ value: `retires (age ${retireAge})`, position: 'insideTopRight', fontSize: 10, fill: '#71717a' }}
              />
              <Area
                type="monotone"
                dataKey="total_net_worth"
                stroke="#87a17e"
                strokeWidth={1.5}
                fill="url(#grad-glide)"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">Year-by-year drawdown</h3>
        <table className="w-full text-xs">
          <thead className="text-zinc-500">
            <tr className="text-left border-b border-zinc-100">
              <th className="py-1.5">Year</th>
              <th className="py-1.5">Age</th>
              <th className="text-right">Income</th>
              <th className="text-right">Expenses</th>
              <th className="text-right">Net worth</th>
            </tr>
          </thead>
          <tbody>
            {focused.map((r) => {
              const retired = r.age >= retireAge;
              return (
                <tr key={r.year} className={`border-b border-zinc-100 last:border-0 ${retired ? 'bg-zinc-50/60' : ''}`}>
                  <td className="py-1.5">{r.year}</td>
                  <td className="py-1.5">
                    {r.age}
                    {retired && <span className="ml-1 text-[10px] text-zinc-400">(retired)</span>}
                  </td>
                  <td className="text-right tabular-nums">{formatINR(r.income, { compact: true })}</td>
                  <td className="text-right tabular-nums">{formatINR(r.expenses, { compact: true })}</td>
                  <td className="text-right tabular-nums font-medium">{formatINR(r.total_net_worth, { compact: true })}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  note,
  accent,
}: {
  label: string;
  value: string;
  note?: string;
  accent?: 'good' | 'bad';
}) {
  const accentClass = accent === 'bad' ? 'text-rose-700' : accent === 'good' ? 'text-emerald-700' : 'text-zinc-800';
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-zinc-400">{label}</div>
      <div className={`text-lg font-semibold tabular-nums mt-0.5 ${accentClass}`}>{value}</div>
      {note && <div className="text-[10px] text-zinc-400 mt-0.5">{note}</div>}
    </div>
  );
}
