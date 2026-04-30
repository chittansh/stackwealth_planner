'use client';

import type { PlanState, Goal } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function GoalsView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const goals = plan.financial_goals;
  if (!goals.length) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        No goals yet. Tell me about retirement, child education, or a property purchase.
      </div>
    );
  }
  const today = new Date().getFullYear();
  const horizon = plan.computed.horizon_years || 45;
  const driver = plan.computed.risk_profile?.need_primary_goal;
  const recommendedScore = plan.computed.risk_profile?.recommended_score ?? 50;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <h3 className="text-sm font-medium text-zinc-700 mb-3">Goal timeline</h3>
      <div className="relative pl-3 border-l-2 border-zinc-100">
        <div className="absolute left-[-3px] top-0 w-2 h-2 rounded-full bg-zinc-300" />
        <div className="text-[11px] uppercase tracking-wide text-zinc-400 mb-2 ml-1">today · {today}</div>
        <ul className="flex flex-col gap-3">
          {goals.map((g) => {
            const status = goalStatus(g, recommendedScore);
            const yr = g.target_year ?? today + (g.horizon_years ?? 10);
            return (
              <li key={g.id} className="flex items-center gap-3">
                <Pill color={status.color}>{status.label}</Pill>
                <div className="flex-1">
                  <div className="flex justify-between text-sm">
                    <span className="text-zinc-800">
                      {g.goal_name}
                      {driver && driver === g.goal_name && <span className="ml-1 text-[10px] text-zinc-400">(driver)</span>}
                    </span>
                    <span className="tabular-nums text-zinc-700">
                      {formatINR(g.target_amount ?? g.today_cost ?? 0, { compact: true })}
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-400">
                    {yr} · priority {g.priority ?? 'important'} · req. return ~{(estReqReturn(g) * 100).toFixed(1)}%
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        <div className="mt-3 ml-1 text-[11px] uppercase tracking-wide text-zinc-400">horizon · {today + horizon}</div>
      </div>
      {plan.computed.risk_profile?.alignment_status === 'goal_risk_mismatch' && (
        <div className="mt-4 rounded-lg bg-amber-50 border border-amber-100 p-3 text-xs text-amber-800">
          One or more goals require more risk than is prudent. Try: increase contribution · extend horizon · reduce
          target · split into essential and aspirational layers.
        </div>
      )}
    </div>
  );
}

function goalStatus(g: Goal, recommendedScore: number): { label: string; color: 'emerald' | 'amber' | 'rose' } {
  const r = estReqReturn(g);
  const need = r <= 0.06 ? 25 : r <= 0.08 ? 40 : r <= 0.10 ? 55 : r <= 0.12 ? 70 : r <= 0.14 ? 85 : 95;
  if (need <= recommendedScore - 10) return { label: 'on track', color: 'emerald' };
  if (need <= recommendedScore + 5) return { label: 'at risk', color: 'amber' };
  return { label: 'unrealistic', color: 'rose' };
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

function Pill({ color, children }: { color: 'emerald' | 'amber' | 'rose'; children: React.ReactNode }) {
  const map = {
    emerald: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-700',
    rose: 'bg-rose-50 text-rose-700',
  } as const;
  return <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full ${map[color]}`}>{children}</span>;
}
