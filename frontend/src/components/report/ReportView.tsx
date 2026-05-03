'use client';

import { useEffect, useState } from 'react';
import { fetchPlan } from '@/lib/api';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

/**
 * Polished print-styled plan summary.
 *
 * Six sections, each starting on its own page:
 *   1. Cover (wordmark + headline projection + freedom score chip)
 *   2. Snapshot (current net worth + risk profile)
 *   3. Allocation (strategic vs recommended in print-friendly bars)
 *   4. Goals timeline
 *   5. Cash flow (first 10 years)
 *   6. Disclaimers
 *
 * All copy is monochrome with matcha as the only accent. Designed to print
 * to A4 cleanly and to read well on screen.
 */
export function ReportView({ householdId }: { householdId: string }) {
  const [plan, setPlan] = useState<PlanState | null>(null);
  useEffect(() => {
    fetchPlan(householdId).then(setPlan).catch(() => undefined);
  }, [householdId]);

  if (!plan) return <p className="p-10 text-zinc-500">Loading…</p>;

  const r = plan.computed.risk_profile;
  const a = plan.computed.allocation;
  const fs = plan.computed.freedom_score;
  const householdName = plan.personal_details.full_name ?? 'Household';
  const generated = new Date().toLocaleDateString('en-IN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  const horizon = plan.computed.horizon_years || 45;
  const finalAmount = plan.computed.headline_amount_at_horizon || 0;

  return (
    <div className="bg-white text-zinc-900 mx-auto max-w-[860px] px-12 py-12 print:p-0 print:max-w-none">
      <ReportStyles />

      {/* Cover ─────────────────────────────────────────────────────────── */}
      <section className="report-page">
        <header className="flex items-center justify-between">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/stackwealth-logo.png" alt="stackwealth" className="h-7 w-auto" />
          <span className="text-[11px] uppercase tracking-[0.2em] text-zinc-400">Plan summary</span>
        </header>

        <div className="mt-32">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-400">prepared for</p>
          <h1 className="serif text-[56px] leading-[1.05] tracking-tight mt-3 text-zinc-900">
            {householdName}
          </h1>
          <p className="mt-4 text-zinc-500">{generated}</p>
        </div>

        <div className="mt-24 grid grid-cols-2 gap-8 border-t border-zinc-200 pt-8">
          <Stat label={`In ${horizon} years, projected net worth`} value={formatINR(finalAmount, { compact: true })} big />
          {fs ? (
            <Stat
              label="Freedom Score"
              value={`${fs.final_score.toFixed(0)} / 100`}
              hint={`Estimated freedom age ${fs.estimated_freedom_age.toFixed(0)}`}
              big
              accent
            />
          ) : (
            <Stat label="Freedom Score" value="—" hint="Add household data to compute" big />
          )}
        </div>
      </section>

      {/* Snapshot ─────────────────────────────────────────────────────── */}
      <section className="report-page">
        <SectionTitle eyebrow="01" title="Snapshot" />
        <div className="grid grid-cols-2 gap-10 mt-8">
          <Block title="Current net worth">
            <Pair label="Assets" value={formatINR(plan.computed.net_worth.assets_total, { compact: true })} />
            <Pair label="Debts" value={formatINR(plan.computed.net_worth.debts_total, { compact: true })} />
            <Pair label="Net" value={formatINR(plan.computed.net_worth.total, { compact: true })} bold />
            <Pair label="Liquid component" value={formatINR(plan.computed.net_worth.liquid, { compact: true })} muted />
          </Block>
          {r ? (
            <Block title="Risk profile">
              <Pair label="Capacity" value={`${r.capacity_score} · ${r.capacity_profile}`} />
              <Pair label="Need" value={`${r.need_score} · ${r.need_profile}`} />
              <Pair label="Willingness" value={`${r.willingness_score} · ${r.willingness_profile}`} />
              <Pair label="Recommended" value={`${r.recommended_score} · ${r.recommended_profile}`} bold />
              <Pair label="Alignment" value={r.alignment_status.replace(/_/g, ' ')} muted />
            </Block>
          ) : (
            <Block title="Risk profile" empty>
              Complete the 3-question risk flow to populate this section.
            </Block>
          )}
        </div>

        {fs && (
          <div className="mt-10">
            <h3 className="text-[13px] uppercase tracking-[0.18em] text-zinc-500 mb-4">Freedom Score · 5 pillars</h3>
            <div className="grid grid-cols-5 gap-4">
              {(['liquidity', 'debt', 'investment', 'discipline', 'risk'] as const).map((k) => (
                <Pillar key={k} label={k} value={fs.pillars[k]} />
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Allocation ───────────────────────────────────────────────────── */}
      {a && (
        <section className="report-page">
          <SectionTitle eyebrow="02" title="Allocation" />
          <p className="text-zinc-500 text-[13px] mt-2">
            Strategic anchor for a <span className="text-zinc-800">{a.investor_risk_band}</span> investor;
            recommended overlay reflects the tactical regime ({a.tactical_regime_label}, score {a.tactical_regime_score}).
          </p>

          <div className="mt-10 space-y-6">
            <AllocBar
              label="Strategic"
              equity={a.strategic_allocation.equity}
              debt={a.strategic_allocation.debt}
              gold={a.strategic_allocation.gold}
              cash={a.strategic_allocation.cash}
              accent={false}
            />
            <AllocBar
              label="Recommended"
              equity={a.recommended_allocation.equity}
              debt={a.recommended_allocation.debt}
              gold={a.recommended_allocation.gold}
              cash={a.recommended_allocation.cash}
              accent
            />
          </div>

          <div className="mt-10 grid grid-cols-2 gap-8">
            <Block title="Equity split (recommended)">
              <Pair label="Large cap" value={`${a.recommended_equity_split.large}%`} />
              <Pair label="Mid cap" value={`${a.recommended_equity_split.mid}%`} />
              <Pair label="Small cap" value={`${a.recommended_equity_split.small}%`} />
              <Pair label="Debt duration" value={a.debt_duration_stance} muted />
            </Block>
            <Block title="Rebalancing actions">
              {a.rebalancing_actions.length === 0 ? (
                <p className="text-zinc-500 text-[13px]">Allocation is in line; no rebalancing needed.</p>
              ) : (
                <ul className="text-[13px] text-zinc-700 space-y-1">
                  {a.rebalancing_actions.map((act, i) => (
                    <li key={i} className="leading-snug">
                      <span className="text-zinc-300 mr-2">·</span>
                      {act}
                    </li>
                  ))}
                </ul>
              )}
            </Block>
          </div>
        </section>
      )}

      {/* Goals ────────────────────────────────────────────────────────── */}
      <section className="report-page">
        <SectionTitle eyebrow={a ? '03' : '02'} title="Goals" />
        {plan.financial_goals.length === 0 ? (
          <p className="text-zinc-500 text-[13px] mt-6">No goals captured yet.</p>
        ) : (
          <ul className="mt-8 space-y-5">
            {plan.financial_goals
              .slice()
              .sort((x, y) => (x.target_year ?? 9999) - (y.target_year ?? 9999))
              .map((g) => (
                <li
                  key={g.id}
                  className="grid grid-cols-[80px_1fr_auto] gap-6 pb-4 border-b border-zinc-100 last:border-0"
                >
                  <span className="serif text-[20px] text-zinc-700 tabular-nums">{g.target_year ?? '—'}</span>
                  <div>
                    <div className="text-[15px] text-zinc-900">{g.goal_name}</div>
                    <div className="text-[12px] text-zinc-500 mt-0.5 capitalize">
                      {g.kind.replace(/_/g, ' ')} · priority {g.priority ?? 'important'}
                      {g.horizon_years ? ` · ${g.horizon_years} yr horizon` : ''}
                    </div>
                  </div>
                  <span className="text-[15px] text-zinc-900 tabular-nums">
                    {formatINR(g.target_amount ?? g.today_cost ?? 0, { compact: true })}
                  </span>
                </li>
              ))}
          </ul>
        )}
      </section>

      {/* Cash flow ────────────────────────────────────────────────────── */}
      <section className="report-page">
        <SectionTitle
          eyebrow={a ? '04' : '03'}
          title="Cash flow"
          subtitle="First ten years — annual figures, inflation-adjusted."
        />
        <table className="w-full mt-8 text-[12px] tabular-nums">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.16em] text-zinc-400 border-b border-zinc-200">
              <Th>Year</Th>
              <Th>Age</Th>
              <Th right>Income</Th>
              <Th right>Expenses</Th>
              <Th right>Taxes</Th>
              <Th right>Total NW</Th>
            </tr>
          </thead>
          <tbody>
            {plan.computed.cash_flow_table.slice(0, 10).map((row) => (
              <tr key={row.year} className="border-b border-zinc-100">
                <Td>{row.year}</Td>
                <Td muted>{row.age}</Td>
                <Td right>{formatINR(row.income, { compact: true })}</Td>
                <Td right>{formatINR(row.expenses, { compact: true })}</Td>
                <Td right muted>
                  {formatINR(row.taxes, { compact: true })}
                </Td>
                <Td right bold>
                  {formatINR(row.total_net_worth, { compact: true })}
                </Td>
              </tr>
            ))}
            {plan.computed.cash_flow_table.length === 0 && (
              <tr>
                <td colSpan={6} className="text-zinc-500 py-6 text-center">
                  Cash flow appears once income and expenses are captured.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {/* Disclaimers ──────────────────────────────────────────────────── */}
      <section className="report-page">
        <SectionTitle eyebrow={a ? '05' : '04'} title="Disclaimers" />
        <p className="mt-6 text-[12px] text-zinc-500 leading-[1.7] max-w-[640px]">
          This plan is generated by Stackwealth Planner from the data captured in the workspace and the
          assumptions shown. It is not investment advice. Past performance does not guarantee future
          returns. Tax and regulatory rules referenced are India-specific (FY24 regime). Confirm with a
          SEBI-registered investment adviser before acting on any specific recommendation.
        </p>
        <div className="mt-12 pt-6 border-t border-zinc-200 flex justify-between text-[11px] text-zinc-400">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/stackwealth-logo.png" alt="stackwealth" className="h-4 w-auto opacity-60" />
          <span>{generated}</span>
        </div>
      </section>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────────

function ReportStyles() {
  return (
    <style>{`
      .serif { font-family: 'Cormorant Garamond', 'Georgia', serif; font-weight: 500; }
      .report-page { padding: 4rem 0; min-height: 90vh; }
      .report-page + .report-page { border-top: 1px solid #f4f4f5; }
      @media print {
        @page { size: A4; margin: 18mm; }
        body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        .report-page { padding: 0; min-height: 0; page-break-after: always; border: 0; }
        .report-page:last-child { page-break-after: auto; }
      }
    `}</style>
  );
}

function SectionTitle({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <header>
      <p className="text-[10px] uppercase tracking-[0.28em] text-zinc-400">{eyebrow}</p>
      <h2 className="serif text-[40px] leading-[1.1] mt-2 text-zinc-900">{title}</h2>
      {subtitle && <p className="text-zinc-500 text-[13px] mt-2">{subtitle}</p>}
    </header>
  );
}

function Stat({
  label,
  value,
  hint,
  big,
  accent,
}: {
  label: string;
  value: string;
  hint?: string;
  big?: boolean;
  accent?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-400">{label}</p>
      <p
        className={`serif mt-2 leading-tight ${big ? 'text-[36px]' : 'text-[20px]'}`}
        style={accent ? { color: 'var(--color-accent)' } : undefined}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-[12px] text-zinc-500">{hint}</p>}
    </div>
  );
}

function Block({
  title,
  children,
  empty,
}: {
  title: string;
  children: React.ReactNode;
  empty?: boolean;
}) {
  return (
    <div>
      <h3 className="text-[10px] uppercase tracking-[0.2em] text-zinc-400 mb-3">{title}</h3>
      {empty ? <p className="text-zinc-500 text-[13px]">{children}</p> : <div>{children}</div>}
    </div>
  );
}

function Pair({
  label,
  value,
  bold,
  muted,
}: {
  label: string;
  value: string;
  bold?: boolean;
  muted?: boolean;
}) {
  return (
    <div className="flex justify-between text-[13px] py-1.5 border-b border-zinc-100 last:border-0">
      <span className={muted ? 'text-zinc-400' : 'text-zinc-500'}>{label}</span>
      <span
        className={`tabular-nums ${
          bold ? 'font-medium text-zinc-900' : muted ? 'text-zinc-500' : 'text-zinc-800'
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function Pillar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-400 capitalize">{label}</div>
      <div className="serif text-[24px] mt-1 text-zinc-900 tabular-nums">{pct.toFixed(0)}</div>
      <div className="mt-2 h-1 rounded-full bg-zinc-100 overflow-hidden">
        <div
          className="h-full"
          style={{
            width: `${pct}%`,
            background: pct >= 70 ? 'var(--color-accent)' : pct >= 50 ? '#a1a1aa' : '#52525b',
          }}
        />
      </div>
    </div>
  );
}

function AllocBar({
  label,
  equity,
  debt,
  gold,
  cash,
  accent,
}: {
  label: string;
  equity: number;
  debt: number;
  gold: number;
  cash: number;
  accent: boolean;
}) {
  const slices = [
    { k: 'Equity', v: equity, c: accent ? '#87a17e' : '#52525b' },
    { k: 'Debt', v: debt, c: accent ? '#a8be9b' : '#a1a1aa' },
    { k: 'Gold', v: gold, c: accent ? '#cbd6c2' : '#d4d4d8' },
    { k: 'Cash', v: cash, c: accent ? '#e7ecdf' : '#e4e4e7' },
  ];
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-[10px] uppercase tracking-[0.2em] text-zinc-400">{label}</span>
        <span className="text-[12px] text-zinc-500">{slices.map((s) => `${s.k} ${s.v}%`).join(' · ')}</span>
      </div>
      <div className="flex h-2 rounded-full overflow-hidden border border-zinc-100">
        {slices.map((s) => (
          <div key={s.k} style={{ width: `${s.v}%`, background: s.c }} title={`${s.k} ${s.v}%`} />
        ))}
      </div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-2 py-2 font-medium ${right ? 'text-right' : 'text-left'}`}>{children}</th>
  );
}

function Td({
  children,
  right,
  bold,
  muted,
}: {
  children: React.ReactNode;
  right?: boolean;
  bold?: boolean;
  muted?: boolean;
}) {
  return (
    <td
      className={`px-2 py-1.5 ${right ? 'text-right' : 'text-left'} ${
        bold ? 'font-medium text-zinc-900' : muted ? 'text-zinc-400' : 'text-zinc-700'
      }`}
    >
      {children}
    </td>
  );
}
