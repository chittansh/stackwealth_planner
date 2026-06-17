'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

type GoalBlock = {
  goal_name?: string;
  goal_id?: string;
  target_year?: number;
  years_to_go?: number;
  future_value_needed?: number;
  required_sip_monthly?: number;
  incremental_sip_monthly?: number;
  affordable_sip_monthly?: number;
  sip_shortfall_monthly?: number;
  funded_share_at_affordable_sip?: number;
};

/**
 * Goal Scenarios — sits on the Net Worth canvas. Compares two regimes:
 *
 *   1. REQUIRED plan: full PMT-derived SIP per goal (every goal at 100%).
 *   2. FEASIBLE plan: required SIPs rationed proportionally to the
 *      household's actual surplus. Shows which goals get under-funded
 *      and by how much.
 *
 * Backed by `plan.computed.cfp.summary` + `plan.computed.cfp.goal_blocks`
 * — the affordability fields are computed in the engine
 * (compute_cfp → goal_block.affordable_sip_monthly /
 * funded_share_at_affordable_sip).
 */
export function GoalScenariosCard({ plan }: { plan: PlanState }) {
  const cfp = plan.computed.cfp;
  if (!cfp) return null;
  const goalBlocks = (cfp.goal_blocks ?? []) as unknown as GoalBlock[];
  if (!goalBlocks.length) return null;
  const s = (cfp.summary ?? {}) as Record<string, number | boolean | undefined>;

  const incrementalRequired = (s.total_incremental_sip_monthly as number) ?? 0;
  const affordableNewSip = (s.affordable_new_sip_monthly as number) ?? 0;
  const affordableSipTotal = (s.affordable_sip_total_monthly as number) ?? 0;
  const rationFactor = (s.sip_ration_factor as number) ?? 1;
  const isAffordable = (s.is_plan_affordable as boolean) ?? incrementalRequired <= affordableNewSip;

  // Per-goal rows for the side-by-side comparison
  const rows = goalBlocks
    .filter((g) => (g.required_sip_monthly ?? 0) > 0 || (g.incremental_sip_monthly ?? 0) > 0)
    .map((g) => ({
      name: g.goal_name ?? 'Unnamed',
      year: g.target_year,
      years: g.years_to_go,
      fv: g.future_value_needed ?? 0,
      requiredSip: g.required_sip_monthly ?? 0,
      incrementalSip: g.incremental_sip_monthly ?? 0,
      affordableSip: g.affordable_sip_monthly ?? 0,
      fundedShare: g.funded_share_at_affordable_sip ?? 1,
    }));

  if (rows.length === 0) return null;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <header className="flex items-baseline justify-between mb-1">
        <h3 className="text-sm font-medium text-zinc-700">Goal scenarios</h3>
        <span
          className={`text-[10px] uppercase tracking-wide ${
            isAffordable ? 'text-[color:var(--color-accent,#5f7d56)]' : 'text-amber-700'
          }`}
        >
          {isAffordable ? 'All goals affordable' : `Rationed at ${(rationFactor * 100).toFixed(0)}% of plan`}
        </span>
      </header>
      <p className="text-[11px] text-zinc-400 mb-4">
        Side-by-side: what the goals demand at full plan vs. what your surplus actually covers. When required
        SIPs exceed available surplus, each goal is proportionally rationed.
      </p>

      {/* Headline tiles — required vs feasible totals */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <ScenarioTile
          label="Required plan"
          subtitle="Every goal fully funded"
          sipTotal={incrementalRequired}
          fundedFraction={1}
          tone="muted"
        />
        <ScenarioTile
          label="Feasible plan"
          subtitle={
            isAffordable
              ? 'Surplus covers everything'
              : `Capped at your monthly surplus (${formatINR(affordableNewSip, { compact: true })})`
          }
          sipTotal={affordableSipTotal}
          fundedFraction={rationFactor}
          tone={isAffordable ? 'matcha' : 'amber'}
        />
      </div>

      {/* Per-goal table */}
      <div className="overflow-x-auto -mx-2 px-2">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-zinc-500 border-b border-zinc-100">
              <th className="py-1.5 font-medium">Goal</th>
              <th className="py-1.5 font-medium text-right">FV needed</th>
              <th className="py-1.5 font-medium text-right">Required SIP</th>
              <th className="py-1.5 font-medium text-right">Feasible SIP</th>
              <th className="py-1.5 font-medium text-right pr-1">Funded</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const fullyFunded = r.fundedShare >= 0.999;
              return (
                <tr key={r.name} className="border-b border-zinc-100 last:border-0">
                  <td className="py-1.5">
                    <div className="text-zinc-800">{r.name}</div>
                    <div className="text-[10px] text-zinc-400">
                      {r.year ? `${r.year} · ${r.years}y` : ''}
                    </div>
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-700">
                    {formatINR(r.fv, { compact: true })}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-700">
                    {formatINR(r.incrementalSip || r.requiredSip, { compact: true })}/mo
                  </td>
                  <td className="py-1.5 text-right tabular-nums">
                    <span className={fullyFunded ? 'text-[color:var(--color-accent,#5f7d56)]' : 'text-amber-700'}>
                      {formatINR(r.affordableSip, { compact: true })}/mo
                    </span>
                  </td>
                  <td className="py-1.5 text-right pr-1">
                    <FundedPill fraction={r.fundedShare} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {!isAffordable && (
        <div className="mt-3 rounded-md bg-amber-50/60 border border-amber-200 p-2.5 text-xs text-amber-800">
          <strong>What to do:</strong> the required SIPs across all goals total{' '}
          <span className="tabular-nums">{formatINR(incrementalRequired, { compact: true })}/mo</span> but your
          surplus is{' '}
          <span className="tabular-nums">{formatINR(affordableNewSip, { compact: true })}/mo</span>. Choose one
          or more: <em>extend horizons</em> (more years = lower required SIP),
          <em> reduce target amounts</em>, <em>raise income</em>, or accept partial funding (~
          {(rationFactor * 100).toFixed(0)}% per goal).
        </div>
      )}
    </div>
  );
}

function ScenarioTile({
  label,
  subtitle,
  sipTotal,
  fundedFraction,
  tone,
}: {
  label: string;
  subtitle: string;
  sipTotal: number;
  fundedFraction: number;
  tone: 'matcha' | 'amber' | 'muted';
}) {
  const wrapperCls =
    tone === 'matcha'
      ? 'bg-[var(--color-accent-soft,#eef3eb)] border-[color:var(--color-accent,#5f7d56)]/20'
      : tone === 'amber'
      ? 'bg-amber-50 border-amber-200'
      : 'bg-zinc-50 border-zinc-200';
  const accentText =
    tone === 'matcha'
      ? 'text-[color:var(--color-accent,#5f7d56)]'
      : tone === 'amber'
      ? 'text-amber-800'
      : 'text-zinc-800';

  return (
    <div className={`rounded-lg border px-3 py-2.5 ${wrapperCls}`}>
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`text-lg font-semibold tabular-nums mt-0.5 ${accentText}`}>
        {formatINR(sipTotal, { compact: true })}
        <span className="text-xs font-normal text-zinc-500"> /mo</span>
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">{subtitle}</div>
      <div className="h-1 mt-2 rounded-full bg-white/70 overflow-hidden">
        <div
          className={`h-full ${
            tone === 'matcha'
              ? 'bg-[color:var(--color-accent,#5f7d56)]'
              : tone === 'amber'
              ? 'bg-amber-500'
              : 'bg-zinc-400'
          }`}
          style={{ width: `${Math.min(100, fundedFraction * 100).toFixed(1)}%` }}
        />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5 tabular-nums">
        {(fundedFraction * 100).toFixed(0)}% of goal targets covered
      </div>
    </div>
  );
}

function FundedPill({ fraction }: { fraction: number }) {
  const pct = Math.min(100, Math.max(0, fraction * 100));
  const isFull = pct >= 99.9;
  const isCritical = pct < 50;
  const cls = isFull
    ? 'bg-[var(--color-accent-soft,#eef3eb)] text-[color:var(--color-accent,#5f7d56)]'
    : isCritical
    ? 'bg-rose-50 text-rose-700'
    : 'bg-amber-50 text-amber-800';
  return (
    <span className={`inline-block text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full tabular-nums ${cls}`}>
      {pct.toFixed(0)}%
    </span>
  );
}
