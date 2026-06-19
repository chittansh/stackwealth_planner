'use client';

import type { PlanState, Goal } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { SuggestedSection } from './SuggestedSection';

/**
 * Mirrors the firm's `10_Financial_Goals` sheet in `Format for inputs for
 * CFP_ng_080626.xlsx`. For each goal we surface:
 *
 *   Today's cost · Inflation · Years to go · Future Value Needed
 *   Asset to Allocate (existing buckets earmarked)
 *   Gap on today's value · FV of unallocated assets
 *   ROI (post-tax) · Monthly SIP needed · Existing SIP · Remaining SIP
 *
 * Source: `plan.computed.cfp.goal_blocks` (Excel-faithful). Falls back to
 * client-side bisect when the snapshot hasn't been computed yet.
 */
export function GoalsView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const goals = plan.financial_goals;
  const today = new Date().getFullYear();
  const horizon = plan.computed.horizon_years || 45;
  const driver = plan.computed.risk_profile?.need_primary_goal;
  const recommendedScore = plan.computed.risk_profile?.recommended_score ?? 50;
  const goalBlocks = (plan.computed.cfp?.goal_blocks as GoalBlock[] | undefined) ?? [];

  // Retirement is a goal too — synthesize a block from the Excel-faithful
  // retirement engine so it appears in the timeline + goal-planning detail
  // alongside the other goals (the firm sheet keeps it on a separate tab).
  const retirementBlock = buildRetirementBlock(plan.computed.cfp?.retirement, today);
  const blocksWithRetire = retirementBlock ? [retirementBlock, ...goalBlocks] : goalBlocks;

  if (!goals.length && !retirementBlock) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        No goals yet. Tell me about retirement, child education, or a property purchase.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">Goal timeline</h3>
        <div className="relative pl-3 border-l-2 border-zinc-100">
          <div className="absolute left-[-3px] top-0 w-2 h-2 rounded-full bg-zinc-300" />
          <div className="text-[11px] uppercase tracking-wide text-zinc-400 mb-2 ml-1">today · {today}</div>
          <ul className="flex flex-col gap-3">
            {retirementBlock && (
              <li className="flex items-center gap-3">
                <Pill tone={(retirementBlock.fv_gap ?? 0) > 0 ? 'muted' : 'matcha'}>
                  {(retirementBlock.fv_gap ?? 0) > 0 ? 'underfunded' : 'on track'}
                </Pill>
                <div className="flex-1">
                  <div className="flex justify-between text-sm">
                    <span className="text-zinc-800">
                      Retirement
                      <span className="ml-1.5 text-[9px] uppercase tracking-wide text-[color:var(--color-accent,#5f7d56)] border border-[color:var(--color-accent,#5f7d56)]/40 rounded px-1 py-0.5">
                        corpus
                      </span>
                    </span>
                    <span className="tabular-nums text-zinc-700">
                      {formatINR(retirementBlock.future_value_needed ?? 0, { compact: true })}
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-400">
                    {retirementBlock.target_year} · priority essential · req. return{' '}
                    {formatReqReturn(retirementBlock.effective_return ?? 0.105)}
                  </div>
                </div>
              </li>
            )}
            {goals.map((g) => {
              const status = goalStatus(g, recommendedScore);
              const yr = g.target_year ?? today + (g.horizon_years ?? 10);
              const block = goalBlocks.find((b) => b.goal_id === g.id || b.goal_name === g.goal_name);
              return (
                <li key={g.id} className="flex items-center gap-3">
                  <Pill tone={status.tone}>{status.label}</Pill>
                  <div className="flex-1">
                    <div className="flex justify-between text-sm">
                      <span className="text-zinc-800">
                        {g.goal_name}
                        {driver && driver === g.goal_name && <span className="ml-1 text-[10px] text-zinc-400">(driver)</span>}
                      </span>
                      <span className="tabular-nums text-zinc-700">
                        {formatINR(block?.future_value_needed ?? g.target_amount ?? g.today_cost ?? 0, { compact: true })}
                      </span>
                    </div>
                    <div className="text-[11px] text-zinc-400">
                      {yr} · priority {g.priority ?? 'important'} · req. return {formatReqReturn(block?.effective_return ?? estReqReturn(g))}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="mt-3 ml-1 text-[11px] uppercase tracking-wide text-zinc-400">horizon · {today + horizon}</div>
        </div>
      </div>

      {blocksWithRetire.length > 0 && <GoalBlocksDetail goals={goals} blocks={blocksWithRetire} />}

      <SuggestedSection plan={plan} domain="goals" />
    </div>
  );
}

type GoalBlock = {
  goal_name: string;
  goal_id?: string;
  target_year?: number;
  years_to_go?: number;
  today_cost?: number;
  inflation_used?: number;
  future_value_needed?: number;
  allocations?: { bucket: string; today_value_used: number }[];
  allocated_today_total?: number;
  gap_today?: number;
  fv_gap?: number;
  effective_return?: number;
  required_sip_monthly?: number;
  existing_sip_monthly?: number;
  incremental_sip_monthly?: number;
  affordable_sip_monthly?: number;
  sip_shortfall_monthly?: number;
  funded_share_at_affordable_sip?: number;
};

/** Synthesize a retirement GoalBlock from the Excel-faithful retirement
 * engine output so retirement shows up as a first-class goal. The funded bar
 * reads (corpus − shortfall)/corpus; SIP cells show gross vs existing vs add. */
function buildRetirementBlock(
  ret: Record<string, unknown> | undefined | null,
  today: number,
): GoalBlock | null {
  if (!ret) return null;
  const n = (k: string) => (typeof ret[k] === 'number' ? (ret[k] as number) : 0);
  const corpus = n('corpus_required');
  if (corpus <= 0) return null;
  const years = Math.round(n('years_to_retire'));
  // Funded the way the firm sheet judges it — via the step-up plan (Section 3),
  // not earmarked assets alone. The funded bar reads the step-up funded-%.
  const stepupFunded = typeof ret['stepup_funded_pct'] === 'number' ? (ret['stepup_funded_pct'] as number) : null;
  const fvGap = stepupFunded != null
    ? Math.max(0, corpus * (1 - stepupFunded / 100))
    : n('corpus_shortfall_after_existing');
  // The realistic ask is the step-up STARTING SIP (grown 10%/yr), not a flat SIP.
  const startReq = n('stepup_required_start_sip_monthly') || n('gross_monthly_sip');
  const ongoing = n('ongoing_retirement_sip_monthly');
  return {
    goal_name: 'Retirement',
    goal_id: '__retirement__',
    target_year: today + years,
    years_to_go: years,
    today_cost: n('annual_expense_today') || n('retirement_annual_expense_today'),
    inflation_used: n('inflation_during_retirement'),
    future_value_needed: corpus,
    allocated_today_total: 0,
    gap_today: 0,
    fv_gap: fvGap,
    effective_return: n('sip_funding_return') || 0.105,
    required_sip_monthly: startReq,
    existing_sip_monthly: ongoing,
    incremental_sip_monthly: n('stepup_additional_start_sip_monthly'),
    affordable_sip_monthly: n('stepup_additional_start_sip_monthly'),
    sip_shortfall_monthly: 0,
    funded_share_at_affordable_sip: 1,
  };
}

function GoalBlocksDetail({ goals, blocks }: { goals: Goal[]; blocks: GoalBlock[] }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <h3 className="text-sm font-medium text-zinc-700 mb-1">Goal planning (Excel-faithful)</h3>
      <p className="text-[11px] text-zinc-400 mb-4">
        Mirrors <code className="text-[10px]">10_Financial_Goals</code> in the firm CFP workbook —
        today&apos;s cost grown by per-goal inflation, existing assets allocated in priority order,
        gap funded via a glide-path SIP.
      </p>
      <div className="flex flex-col gap-4">
        {blocks.map((b) => {
          const goal = goals.find((g) => g.id === b.goal_id || g.goal_name === b.goal_name);
          const importance = b.goal_name === 'Retirement'
            ? 'Essential'
            : goal?.priority === 'essential' ? 'Essential' : goal?.priority === 'aspirational' ? 'Desirable' : 'Important';
          const fundedPct = (b.future_value_needed ?? 0) > 0
            ? Math.max(0, Math.min(100, ((b.future_value_needed! - (b.fv_gap ?? 0)) / b.future_value_needed!) * 100))
            : 0;
          return (
            <div key={b.goal_id ?? b.goal_name} className="rounded-lg border border-zinc-200 bg-zinc-50/40 p-4">
              <div className="flex items-baseline justify-between mb-2">
                <div className="flex items-baseline gap-3">
                  <span className="text-sm font-medium text-zinc-800">{b.goal_name}</span>
                  <span className="text-[10px] uppercase tracking-wide text-zinc-500">{importance}</span>
                  {b.target_year != null && (
                    <span className="text-[11px] text-zinc-500">target {b.target_year} · {b.years_to_go}y</span>
                  )}
                </div>
                <span className="text-[10px] text-zinc-500">
                  ROI {((b.effective_return ?? 0) * 100).toFixed(1)}%
                </span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                <Cell label="Today's cost" value={formatINR(b.today_cost ?? 0, { compact: true })} />
                <Cell
                  label="Inflation"
                  value={`${((b.inflation_used ?? 0) * 100).toFixed(1)}%`}
                />
                <Cell
                  label="Future Value Needed"
                  value={formatINR(b.future_value_needed ?? 0, { compact: true })}
                  emphasis
                />
                <Cell
                  label="Allocated (today)"
                  value={formatINR(b.allocated_today_total ?? 0, { compact: true })}
                />
                <Cell
                  label="Gap on today's value"
                  value={formatINR(b.gap_today ?? 0, { compact: true })}
                />
                <Cell
                  label="FV of gap"
                  value={formatINR(b.fv_gap ?? 0, { compact: true })}
                />
                <Cell
                  label="SIP needed"
                  value={formatINR(b.required_sip_monthly ?? 0, { compact: true }) + '/mo'}
                  emphasis
                />
                <Cell
                  label="Existing SIP"
                  value={formatINR(b.existing_sip_monthly ?? 0, { compact: true }) + '/mo'}
                />
              </div>

              {(b.incremental_sip_monthly ?? 0) > 0 && (
                <FeasibilityRow
                  required={b.incremental_sip_monthly ?? 0}
                  affordable={b.affordable_sip_monthly ?? b.incremental_sip_monthly ?? 0}
                  shortfall={b.sip_shortfall_monthly ?? 0}
                  fundedShare={b.funded_share_at_affordable_sip ?? 1}
                />
              )}

              {/* Bucket allocation breakdown */}
              {b.allocations && b.allocations.length > 0 && (
                <div className="mt-3">
                  <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
                    Assets earmarked (priority order)
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {b.allocations.map((a) => (
                      <span key={a.bucket} className="text-[10px] bg-white border border-zinc-200 rounded-full px-2 py-0.5 text-zinc-700">
                        {labelForBucket(a.bucket)} · {formatINR(a.today_value_used, { compact: true })}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Funded progress bar */}
              <div className="mt-3">
                <div className="h-1.5 bg-zinc-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[color:var(--color-accent,#5f7d56)]"
                    style={{ width: `${fundedPct}%` }}
                  />
                </div>
                <div className="text-[10px] text-zinc-500 mt-1 tabular-nums">{fundedPct.toFixed(1)}% funded from existing assets</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function labelForBucket(key: string): string {
  const map: Record<string, string> = {
    weak_stocks: 'Weak stocks',
    weak_mfs: 'Weak MFs',
    fixed_deposits: 'Fixed deposits',
    bonds: 'Bonds',
    neutral_stocks: 'Neutral stocks',
    neutral_mfs: 'Neutral MFs',
    ulips: 'ULIPs',
    nsc: 'NSC',
    ppf: 'PPF',
    gold: 'Gold',
    epf: 'EPF',
    real_estate_for_sale: 'Real estate (for sale)',
  };
  return map[key] ?? key.replace(/_/g, ' ');
}

function Cell({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <span className={`tabular-nums ${emphasis ? 'text-zinc-900 font-medium' : 'text-zinc-800'}`}>{value}</span>
    </div>
  );
}

function FeasibilityRow({
  required,
  affordable,
  shortfall,
  fundedShare,
}: {
  required: number;
  affordable: number;
  shortfall: number;
  fundedShare: number;
}) {
  const fully = shortfall <= 0;
  const pct = Math.min(100, Math.max(0, fundedShare * 100));

  return (
    <div className={`mt-3 rounded-md border px-3 py-2.5 ${fully ? 'bg-white border-zinc-200' : 'bg-amber-50 border-amber-200'}`}>
      <div className="flex items-baseline justify-between text-xs mb-1">
        <span className="text-zinc-500 uppercase tracking-wide text-[10px]">SIP feasibility</span>
        {fully ? (
          <span className="text-[10px] text-[color:var(--color-accent,#5f7d56)]">✓ surplus covers this</span>
        ) : (
          <span className="text-[10px] text-amber-700">
            funds ~{pct.toFixed(0)}% of this goal at current surplus
          </span>
        )}
      </div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-zinc-700">Required SIP</span>
        <span className="text-zinc-900 tabular-nums">{formatINR(required, { compact: true })}/mo</span>
      </div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-zinc-700">Feasible SIP (after rationing surplus)</span>
        <span className={`tabular-nums ${fully ? 'text-zinc-900' : 'text-amber-800'} font-medium`}>
          {formatINR(affordable, { compact: true })}/mo
        </span>
      </div>
      {!fully && shortfall > 0 && (
        <div className="mt-1.5 pt-1.5 border-t border-dashed border-amber-200 flex items-baseline justify-between text-xs">
          <span className="text-amber-800">Shortfall</span>
          <span className="text-amber-800 font-medium tabular-nums">−{formatINR(shortfall, { compact: true })}/mo</span>
        </div>
      )}
      <div className="h-1 mt-2 rounded-full bg-zinc-100 overflow-hidden">
        <div
          className={`h-full ${fully ? 'bg-[color:var(--color-accent,#5f7d56)]' : 'bg-amber-500'}`}
          style={{ width: `${pct.toFixed(1)}%` }}
        />
      </div>
    </div>
  );
}

function goalStatus(g: Goal, recommendedScore: number): { label: string; tone: 'matcha' | 'muted' | 'dark' } {
  const r = estReqReturn(g);
  const need = r <= 0.06 ? 25 : r <= 0.08 ? 40 : r <= 0.10 ? 55 : r <= 0.12 ? 70 : r <= 0.14 ? 85 : 95;
  if (need <= recommendedScore - 10) return { label: 'on track', tone: 'matcha' };
  return { label: 'at risk', tone: 'muted' };
}

const REQ_RETURN_CEILING = 0.30;

function formatReqReturn(r: number): string {
  if (r <= 0.0005) return '0% (fully funded)';
  if (r >= REQ_RETURN_CEILING - 0.001) return '≥30%/yr (unreachable)';
  return `~${(r * 100).toFixed(1)}%`;
}

function estReqReturn(g: Goal): number {
  if (typeof g.required_return_override === 'number') return g.required_return_override;
  const pv = g.current_allocated_amount ?? 0;
  const pmt = (g.periodic_contribution ?? 0) * (g.contribution_frequency === 'monthly' ? 12 : 1);
  const n = g.horizon_years ?? 10;
  let target = g.target_amount ?? 0;
  if (g.is_target_in_today_money && g.inflation_assumed) {
    target = target * Math.pow(1 + g.inflation_assumed, n);
  }
  if (target <= 0 || n <= 0) return 0;
  let lo = 0, hi = 0.30;
  const f = (r: number) => (r === 0 ? pv + pmt * n - target : pv * Math.pow(1 + r, n) + pmt * (Math.pow(1 + r, n) - 1) / r - target);
  if (f(lo) >= 0) return 0;
  if (f(hi) <= 0) return 0.30;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    if (f(mid) < 0) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

function Pill({ tone, children }: { tone: 'matcha' | 'muted' | 'dark'; children: React.ReactNode }) {
  const map = {
    matcha: 'bg-[var(--color-accent-soft)] text-[color:var(--color-accent)]',
    muted: 'bg-zinc-100 text-zinc-600',
    dark: 'bg-zinc-200 text-zinc-800',
  } as const;
  return (
    <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full ${map[tone]}`}>{children}</span>
  );
}
