'use client';

import type { PlanState } from '@/types/plan-state';

/**
 * Slim banner above the canvas that summarises the risk profile, or — when
 * unset — explains the gate. The chat-side RiskGate handles the 3-question
 * flow itself; this is just a status indicator.
 */
export function RiskBanner({ plan }: { plan: PlanState | null }) {
  const r = plan?.computed.risk_profile;

  if (!r) {
    return (
      <div className="mt-3 rounded-lg bg-zinc-50 border border-zinc-200 px-3 py-2 text-xs text-zinc-600 inline-block">
        Risk profile not set. Allocation, tax, and Monte Carlo are gated until you answer 3 quick questions in chat.
      </div>
    );
  }

  return (
    <div className="mt-3 inline-flex items-center gap-3 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs">
      <Stat label="Capacity" value={`${r.capacity_score} (${r.capacity_profile.split(' ')[0]})`} />
      <Sep />
      <Stat label="Need" value={`${r.need_score} (${r.need_profile.split(' ')[0]})`} />
      <Sep />
      <Stat label="Willingness" value={`${r.willingness_score} (${r.willingness_profile.split(' ')[0]})`} />
      <Sep />
      <Stat label="Recommended" value={`${r.recommended_score} · ${r.recommended_profile}`} bold />
      {r.alignment_status !== 'aligned' && (
        <span className="ml-2 text-zinc-500 capitalize">{r.alignment_status.replace(/_/g, ' ')}</span>
      )}
    </div>
  );
}

function Stat({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <span>
      <span className="text-zinc-400">{label}</span>{' '}
      <span className={`tabular-nums ${bold ? 'text-zinc-900 font-medium' : 'text-zinc-700'}`}>{value}</span>
    </span>
  );
}

function Sep() {
  return <span className="text-zinc-300">·</span>;
}
