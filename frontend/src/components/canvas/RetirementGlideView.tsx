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

  const cfpRet = plan.computed.cfp?.retirement as CfpRetirementBlock | undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Stat label="Current age" value={`${startAge}`} note={`retire at ${retireAge}`} />
        <Stat
          label={`Net worth at ${retireAge}`}
          value={formatINR(retireRow?.total_net_worth ?? 0, { compact: true })}
          note={`year ${retireYear}`}
        />
        <Stat
          label={`Terminal (age ${terminalRow.age})`}
          value={formatINR(terminalRow.total_net_worth, { compact: true })}
          note={`${drawdownYears}y in retirement`}
        />
      </div>

      {cfpRet && <RetirementCorpusBlock block={cfpRet} retireAge={retireAge} />}

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

type CfpRetirementBlock = {
  current_age?: number;
  retirement_age?: number;
  life_expectancy?: number;
  years_to_retire?: number;
  years_post_retirement?: number;
  annual_expense_today?: number;
  annual_expense_at_retirement?: number;
  pre_retire_return?: number;
  post_retire_return?: number;
  inflation_during_retirement?: number;
  real_return_during_retirement?: number;
  corpus_required?: number;
  existing_retirement_assets_fv?: number;
  corpus_shortfall_after_existing?: number;
  required_monthly_sip?: number;
};

/** Mirrors the firm's `Retirement Plan` sheet — corpus math, existing FV,
 * shortfall, and the additional monthly SIP to close the gap. */
function RetirementCorpusBlock({ block, retireAge }: { block: CfpRetirementBlock; retireAge: number }) {
  const required = block.corpus_required ?? 0;
  const existingFV = block.existing_retirement_assets_fv ?? 0;
  const shortfall = block.corpus_shortfall_after_existing ?? Math.max(0, required - existingFV);
  const fundedPct = required > 0 ? Math.max(0, Math.min(100, (existingFV / required) * 100)) : 0;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <h3 className="text-sm font-medium text-zinc-700 mb-1">Retirement corpus (Excel-faithful)</h3>
      <p className="text-[11px] text-zinc-400 mb-4">
        Mirrors <code className="text-[10px]">Retirement Plan</code> in the firm CFP workbook —
        inflation-grown expenses at retirement, annuity-due PV of post-retirement years, netted
        against EPF/PPF/NPS future value, and the additional monthly SIP that closes the gap.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <Cell label="Time to retire" value={`${block.years_to_retire ?? '—'} yrs`} />
        <Cell label="Years post-retirement" value={`${block.years_post_retirement ?? '—'} yrs`} />
        <Cell
          label="Annual expense today"
          value={formatINR(block.annual_expense_today ?? 0, { compact: true })}
        />
        <Cell
          label={`Annual expense at age ${retireAge}`}
          value={formatINR(block.annual_expense_at_retirement ?? 0, { compact: true })}
        />
        <Cell
          label="Pre-retire return"
          value={`${((block.pre_retire_return ?? 0) * 100).toFixed(1)}%`}
        />
        <Cell
          label="Post-retire return"
          value={`${((block.post_retire_return ?? 0) * 100).toFixed(1)}%`}
        />
        <Cell
          label="Inflation in retirement"
          value={`${((block.inflation_during_retirement ?? 0) * 100).toFixed(1)}%`}
        />
        <Cell
          label="Inflation-adj real return"
          value={`${((block.real_return_during_retirement ?? 0) * 100).toFixed(2)}%`}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
        <Big label="Corpus required" value={formatINR(required, { compact: true })} />
        <Big label="Existing retirement FV" value={formatINR(existingFV, { compact: true })} subtle />
        <Big label="Shortfall" value={formatINR(shortfall, { compact: true })} accent={shortfall > 0 ? 'bad' : 'good'} />
      </div>

      <div className="mt-4">
        <div className="flex justify-between text-[11px] text-zinc-500 mb-1">
          <span>EPF / PPF / NPS coverage of required corpus</span>
          <span className="tabular-nums">{fundedPct.toFixed(1)}%</span>
        </div>
        <div className="h-2 bg-zinc-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-[color:var(--color-accent,#5f7d56)]"
            style={{ width: `${fundedPct}%` }}
          />
        </div>
      </div>

      {(block.required_monthly_sip ?? 0) > 0 && (
        <div className="mt-4 rounded-md bg-zinc-50 border border-zinc-200 px-3 py-2 text-xs flex justify-between items-center">
          <span className="text-zinc-500">Additional monthly SIP needed to close shortfall</span>
          <span className="text-zinc-900 font-medium tabular-nums">
            {formatINR(block.required_monthly_sip ?? 0)} /mo
          </span>
        </div>
      )}
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <span className="tabular-nums text-zinc-800">{value}</span>
    </div>
  );
}

function Big({ label, value, subtle, accent }: { label: string; value: string; subtle?: boolean; accent?: 'good' | 'bad' }) {
  const cls = accent === 'bad' ? 'text-rose-700' : accent === 'good' ? 'text-emerald-700' : subtle ? 'text-zinc-700' : 'text-zinc-900';
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50/40 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`text-base font-semibold tabular-nums mt-0.5 ${cls}`}>{value}</div>
    </div>
  );
}
