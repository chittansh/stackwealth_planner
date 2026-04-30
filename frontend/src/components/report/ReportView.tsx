'use client';

import { useEffect, useState } from 'react';
import { fetchPlan } from '@/lib/api';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function ReportView({ householdId }: { householdId: string }) {
  const [plan, setPlan] = useState<PlanState | null>(null);
  useEffect(() => {
    fetchPlan(householdId).then(setPlan).catch(() => undefined);
  }, [householdId]);

  if (!plan) return <p className="p-10">Loading…</p>;

  const r = plan.computed.risk_profile;
  const a = plan.computed.allocation;
  const fs = plan.computed.freedom_score;

  return (
    <div className="bg-white text-zinc-900 mx-auto max-w-[920px] p-12 print:p-0 print:max-w-none">
      <style>{`
        @media print {
          .page-break { page-break-after: always; }
          body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        }
      `}</style>

      <section className="page-break">
        <p className="text-xs uppercase tracking-wide text-zinc-400">Stackwealth Planner — Plan summary</p>
        <h1 className="text-4xl font-medium mt-2">{plan.personal_details.full_name ?? 'Household'}</h1>
        <p className="mt-1 text-zinc-500">Generated {new Date().toLocaleDateString('en-IN')}</p>

        <div className="mt-10 border-t border-zinc-200 pt-6">
          <p className="text-sm text-zinc-500">Headline projection</p>
          <h2 className="text-3xl font-medium mt-1">
            In {plan.computed.horizon_years} years you’ll have{' '}
            {formatINR(plan.computed.headline_amount_at_horizon, { compact: true })}
          </h2>
          {fs && (
            <p className="text-sm text-zinc-600 mt-2">
              Freedom Score <span className="font-medium">{fs.final_score.toFixed(0)}</span> /100 ·
              estimated freedom age {fs.estimated_freedom_age}
            </p>
          )}
        </div>
      </section>

      <Section title="Current net worth">
        <Pair label="Assets" value={formatINR(plan.computed.net_worth.assets_total, { compact: true })} />
        <Pair label="Debts" value={formatINR(plan.computed.net_worth.debts_total, { compact: true })} />
        <Pair label="Total" value={formatINR(plan.computed.net_worth.total, { compact: true })} bold />
      </Section>

      {r && (
        <Section title="Risk profile">
          <Pair label="Capacity" value={`${r.capacity_score} (${r.capacity_profile})`} />
          <Pair label="Need" value={`${r.need_score} (${r.need_profile})`} />
          <Pair label="Willingness" value={`${r.willingness_score} (${r.willingness_profile})`} />
          <Pair label="Recommended" value={`${r.recommended_score} · ${r.recommended_profile}`} bold />
          <Pair label="Alignment" value={r.alignment_status.replace(/_/g, ' ')} />
        </Section>
      )}

      {a && (
        <Section title="Allocation">
          <Pair
            label="Strategic"
            value={`E ${a.strategic_allocation.equity}% · D ${a.strategic_allocation.debt}% · G ${a.strategic_allocation.gold}% · C ${a.strategic_allocation.cash}%`}
          />
          <Pair
            label="Recommended"
            value={`E ${a.recommended_allocation.equity}% · D ${a.recommended_allocation.debt}% · G ${a.recommended_allocation.gold}% · C ${a.recommended_allocation.cash}%`}
            bold
          />
          <Pair label="Regime" value={`${a.tactical_regime_label} (${a.tactical_regime_score})`} />
        </Section>
      )}

      <Section title="Goals">
        {plan.financial_goals.length === 0 ? (
          <p className="text-sm text-zinc-500">No goals set.</p>
        ) : (
          <ul className="text-sm space-y-1.5">
            {plan.financial_goals.map((g) => (
              <li key={g.id} className="flex justify-between">
                <span>
                  {g.goal_name} · {g.target_year ?? '—'}
                </span>
                <span className="tabular-nums">{formatINR(g.target_amount ?? g.today_cost ?? 0, { compact: true })}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Cash flow (first 10 years)">
        <table className="w-full text-xs tabular-nums">
          <thead className="text-zinc-400">
            <tr>
              <th className="text-left">Yr</th>
              <th className="text-right">Income</th>
              <th className="text-right">Expenses</th>
              <th className="text-right">Total NW</th>
            </tr>
          </thead>
          <tbody>
            {plan.computed.cash_flow_table.slice(0, 10).map((r) => (
              <tr key={r.year} className="border-t border-zinc-100">
                <td>{r.year}</td>
                <td className="text-right">{formatINR(r.income, { compact: true })}</td>
                <td className="text-right">{formatINR(r.expenses, { compact: true })}</td>
                <td className="text-right">{formatINR(r.total_net_worth, { compact: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Disclaimers">
        <p className="text-xs text-zinc-500 leading-relaxed">
          This plan is generated by Stackwealth Planner from the data captured in the workspace and the assumptions
          shown. It is not investment advice. Past performance does not guarantee future returns. Tax and regulatory
          rules referenced are India-specific (FY24 regime). Confirm with a SEBI-registered investment adviser before
          acting on any specific recommendation.
        </p>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8 border-t border-zinc-200 pt-5 page-break">
      <h3 className="text-sm uppercase tracking-wide text-zinc-400 mb-3">{title}</h3>
      <div>{children}</div>
    </section>
  );
}

function Pair({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex justify-between text-sm py-1.5 border-b border-zinc-100 last:border-0">
      <span className="text-zinc-600">{label}</span>
      <span className={`tabular-nums ${bold ? 'font-medium text-zinc-900' : 'text-zinc-800'}`}>{value}</span>
    </div>
  );
}
