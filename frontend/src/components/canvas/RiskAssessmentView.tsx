'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

/**
 * Risk Assessment & Planning view — a dedicated page that surfaces every
 * dimension the `risk_assess` skill computes:
 *   • Recommended profile (the headline)
 *   • Capacity vs Need vs Willingness, the three scores that drove it
 *   • Which cap was binding on capacity (horizon / EF / surplus / stability)
 *   • Which goal drove the need score, and the alignment between need and
 *     prudent ceiling
 *   • Allocation buckets that fell out of the chosen profile
 *   • Required life + medical cover (read off the freedom score)
 *   • Warnings + suggested goal actions when there's a mismatch
 */
export function RiskAssessmentView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const risk = plan.computed.risk_profile;
  const freedom = plan.computed.freedom_score;
  const allocation = plan.computed.allocation;

  if (!risk) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Risk profile not set yet. Answer the 3 quick questions in chat and this
        page will fill in with your capacity / need / willingness analysis,
        the recommended allocation glide, and the required insurance cover.
      </div>
    );
  }

  const alignmentLabel = ALIGNMENT_LABEL[risk.alignment_status] ?? risk.alignment_status;
  const alignmentTone = ALIGNMENT_TONE[risk.alignment_status] ?? 'neutral';

  return (
    <div className="flex flex-col gap-5">
      {/* ── Headline: recommended profile + alignment status ─────────────── */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6">
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-zinc-400">Recommended risk profile</div>
            <div className="text-2xl font-semibold mt-1">{risk.recommended_profile}</div>
            <div className="text-xs text-zinc-500 mt-1">
              Score <span className="tabular-nums font-medium text-zinc-700">{risk.recommended_score}</span> /100 ·
              prudent ceiling <span className="tabular-nums font-medium text-zinc-700">{risk.prudent_ceiling}</span>
            </div>
          </div>
          <span className={`px-3 py-1 rounded-full text-xs font-medium ${TONE_PILL[alignmentTone]}`}>
            {alignmentLabel}
          </span>
        </div>

        <p className="text-sm text-zinc-600 mt-4 leading-relaxed">
          {ALIGNMENT_EXPLAINER[risk.alignment_status] ?? ''}
        </p>
      </div>

      {/* ── Three-score gauge ────────────────────────────────────────────── */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6">
        <h3 className="text-sm font-medium text-zinc-700 mb-4">The three pillars</h3>
        <div className="flex flex-col gap-4">
          <ScoreBar
            label="Capacity"
            score={risk.capacity_score}
            profile={risk.capacity_profile}
            sub={`Binding cap: ${humanizeCap(risk.capacity_binding_cap)}`}
            tone="capacity"
          />
          <ScoreBar
            label="Need"
            score={risk.need_score}
            profile={risk.need_profile}
            sub={
              risk.need_primary_goal
                ? `Driver: ${risk.need_primary_goal}${risk.need_driver_goals.length > 1 ? ` + ${risk.need_driver_goals.length - 1} more` : ''}`
                : 'No investable goals yet'
            }
            tone="need"
          />
          <ScoreBar
            label="Willingness"
            score={risk.willingness_score}
            profile={risk.willingness_profile}
            sub={
              risk.willingness_raw_score && Math.abs(risk.willingness_raw_score - risk.willingness_score) > 1
                ? `Raw score ${Math.round(risk.willingness_raw_score)}, capped by reaction question`
                : 'From the 3-question questionnaire'
            }
            tone="willingness"
          />
        </div>
        <div className="mt-5 pt-4 border-t border-zinc-100 text-xs text-zinc-500">
          Recommended is the smaller of (capacity, willingness), then matched against need —
          you get whichever profile keeps the plan prudent while still funding the priority goals.
        </div>
      </div>

      {/* ── Warnings + goal actions ──────────────────────────────────────── */}
      {(risk.key_warnings.length > 0 || risk.goal_actions.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {risk.key_warnings.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
              <h3 className="text-sm font-medium text-amber-900 mb-2">Watch-outs</h3>
              <ul className="flex flex-col gap-2 text-sm text-amber-900">
                {risk.key_warnings.map((w, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-amber-500 mt-[2px]">⚠</span>
                    <span className="leading-snug">{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {risk.goal_actions.length > 0 && (
            <div className="rounded-xl border border-zinc-200 bg-white p-5">
              <h3 className="text-sm font-medium text-zinc-700 mb-2">Levers to close the gap</h3>
              <ul className="flex flex-col gap-1.5 text-sm text-zinc-700">
                {risk.goal_actions.map((a, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-zinc-400 mt-[2px]">→</span>
                    <span className="leading-snug">{a}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ── Allocation breakdown (only when computed) ───────────────────── */}
      {allocation && (
        <div className="rounded-xl border border-zinc-200 bg-white p-6">
          <header className="flex items-baseline justify-between flex-wrap gap-2 mb-4">
            <h3 className="text-sm font-medium text-zinc-700">
              Recommended allocation
              <span className="ml-2 text-xs text-zinc-400 font-normal">
                based on {risk.recommended_profile.toLowerCase()}
              </span>
            </h3>
            {allocation.tactical_regime_label && (
              <span className="text-xs text-zinc-500">
                Tactical regime: <span className="font-medium text-zinc-700">{allocation.tactical_regime_label}</span>
              </span>
            )}
          </header>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <AllocBucket label="Equity" pct={allocation.recommended_allocation.equity} tone="eq" />
            <AllocBucket label="Debt" pct={allocation.recommended_allocation.debt} tone="dt" />
            <AllocBucket label="Gold" pct={allocation.recommended_allocation.gold} tone="gd" />
            <AllocBucket label="Cash" pct={allocation.recommended_allocation.cash} tone="cs" />
          </div>
          <div className="mt-4 pt-4 border-t border-zinc-100">
            <div className="text-xs text-zinc-500 mb-2">Equity sub-split</div>
            <div className="flex flex-wrap gap-3 text-xs text-zinc-600">
              <SubSplit label="Large cap" pct={allocation.recommended_equity_split.large} />
              <SubSplit label="Mid cap" pct={allocation.recommended_equity_split.mid} />
              <SubSplit label="Small cap" pct={allocation.recommended_equity_split.small} />
            </div>
          </div>
          {allocation.rebalancing_actions.length > 0 && (
            <div className="mt-4 pt-4 border-t border-zinc-100">
              <div className="text-xs text-zinc-500 mb-2">Next rebalancing actions</div>
              <ul className="flex flex-col gap-1 text-sm text-zinc-700">
                {allocation.rebalancing_actions.slice(0, 5).map((a, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-zinc-400 mt-[2px]">→</span>
                    <span className="leading-snug">{a}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ── Insurance cover required (from freedom score) ───────────────── */}
      {freedom && (freedom.required_life_cover > 0 || freedom.required_medical_cover > 0) && (
        <div className="rounded-xl border border-zinc-200 bg-white p-6">
          <h3 className="text-sm font-medium text-zinc-700 mb-3">
            Insurance cover the plan needs
            {freedom.city_cover_multiplier && freedom.city_cover_multiplier !== 1 && (
              <span className="ml-2 text-xs text-zinc-400 font-normal">
                metro-adjusted × {freedom.city_cover_multiplier.toFixed(2)}
              </span>
            )}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <CoverCard
              label="Term life cover"
              required={freedom.required_life_cover}
              actual={plan.insurance_details?.term_plan?.cover_amount ?? 0}
            />
            <CoverCard
              label="Health cover"
              required={freedom.required_medical_cover}
              actual={
                (plan.insurance_details?.health_insurance?.cover_amount ?? 0) +
                (plan.insurance_details?.family_floater?.cover_amount ?? 0)
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ── helpers ────────────────────────────────────────────────────────────

const ALIGNMENT_LABEL: Record<string, string> = {
  aligned: 'Aligned',
  need_below_ceiling: 'Headroom available',
  goal_risk_mismatch: 'Goals demand more risk than is prudent',
  need_unavailable: 'No investable goals yet',
  incomplete: 'Incomplete inputs',
};

const ALIGNMENT_TONE: Record<string, 'good' | 'bad' | 'neutral'> = {
  aligned: 'good',
  need_below_ceiling: 'good',
  goal_risk_mismatch: 'bad',
  need_unavailable: 'neutral',
  incomplete: 'neutral',
};

const TONE_PILL: Record<string, string> = {
  good: 'bg-emerald-100 text-emerald-800',
  bad: 'bg-rose-100 text-rose-800',
  neutral: 'bg-zinc-100 text-zinc-700',
};

const ALIGNMENT_EXPLAINER: Record<string, string> = {
  aligned:
    'Your goals can be funded inside the risk level your capacity and temperament can absorb — no plan changes needed on the risk dimension.',
  need_below_ceiling:
    'You have more risk capacity than your goals require. The recommended profile keeps the plan prudent rather than chasing unnecessary returns.',
  goal_risk_mismatch:
    'Your goals would need a higher risk profile than is prudent. The recommended profile holds the line on prudence — see the levers below to close the gap.',
  need_unavailable:
    'No investable goals are set yet, so the recommendation falls back to capacity-and-willingness alone. Add a retirement / house / education goal for a sharper signal.',
  incomplete:
    'Some inputs (income, expenses, goals, or liquid assets) are missing — fill them in to sharpen the recommendation.',
};

function humanizeCap(name: string): string {
  const map: Record<string, string> = {
    horizon: 'goal horizon',
    stability: 'income stability',
    ef: 'emergency fund depth',
    surplus: 'monthly surplus',
    exp: 'investing experience',
  };
  return map[name] ?? name;
}

function ScoreBar({
  label,
  score,
  profile,
  sub,
  tone,
}: {
  label: string;
  score: number;
  profile: string;
  sub: string;
  tone: 'capacity' | 'need' | 'willingness';
}) {
  const colour = tone === 'capacity' ? '#87a17e' : tone === 'need' ? '#c08552' : '#7b8db5';
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm mb-1.5">
        <span className="text-zinc-700">
          {label}
          <span className="ml-2 text-xs text-zinc-400">{profile}</span>
        </span>
        <span className="tabular-nums font-medium text-zinc-900">{score}<span className="text-xs text-zinc-400">/100</span></span>
      </div>
      <div className="h-2 rounded-full bg-zinc-100 overflow-hidden">
        <div
          className="h-full rounded-full transition-[width]"
          style={{ width: `${Math.max(0, Math.min(100, score))}%`, backgroundColor: colour }}
        />
      </div>
      <div className="mt-1 text-[11px] text-zinc-500">{sub}</div>
    </div>
  );
}

function AllocBucket({ label, pct, tone }: { label: string; pct: number; tone: 'eq' | 'dt' | 'gd' | 'cs' }) {
  const bg =
    tone === 'eq'
      ? 'bg-emerald-50 text-emerald-900'
      : tone === 'dt'
      ? 'bg-slate-50 text-slate-900'
      : tone === 'gd'
      ? 'bg-amber-50 text-amber-900'
      : 'bg-sky-50 text-sky-900';
  return (
    <div className={`rounded-lg px-4 py-3 ${bg}`}>
      <div className="text-[10px] uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-2xl font-semibold tabular-nums mt-0.5">
        {Math.round(pct)}<span className="text-base opacity-60">%</span>
      </div>
    </div>
  );
}

function SubSplit({ label, pct }: { label: string; pct: number }) {
  return (
    <span className="px-2 py-1 rounded bg-zinc-50 border border-zinc-100">
      {label} <span className="tabular-nums font-medium text-zinc-900">{Math.round(pct)}%</span>
    </span>
  );
}

function CoverCard({ label, required, actual }: { label: string; required: number; actual: number }) {
  const gap = required - actual;
  const tone =
    actual >= required ? 'good' : actual >= required * 0.8 ? 'partial' : 'short';
  const bg =
    tone === 'good'
      ? 'border-emerald-200 bg-emerald-50/40'
      : tone === 'partial'
      ? 'border-amber-200 bg-amber-50/40'
      : 'border-rose-200 bg-rose-50/40';
  const status =
    tone === 'good'
      ? 'Adequate'
      : tone === 'partial'
      ? `Short by ${formatINR(gap, { compact: true })}`
      : `Underinsured — gap ${formatINR(gap, { compact: true })}`;
  return (
    <div className={`rounded-lg border ${bg} px-4 py-3`}>
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="flex items-baseline justify-between mt-1">
        <span className="text-sm text-zinc-600">
          Required <span className="tabular-nums font-medium text-zinc-900">{formatINR(required, { compact: true })}</span>
        </span>
        <span className="text-sm text-zinc-600">
          You have <span className="tabular-nums font-medium text-zinc-900">{formatINR(actual, { compact: true })}</span>
        </span>
      </div>
      <div className="mt-1.5 text-xs text-zinc-700">{status}</div>
    </div>
  );
}
