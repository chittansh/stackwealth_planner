'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

type InsuranceBlock = {
  human_life_value?: number;
  needs_based_corpus?: number;
  average?: number;
  total_need_including_loans?: number;
  existing_cover?: number;
  investable_assets?: number;
  additional_cover_required?: number;
  health?: {
    required?: number;
    existing_cover?: number;
    additional_cover_required?: number;
    family_base?: number;
    senior_parent_cover?: number;
  };
};

export function InsuranceView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const ins = plan.insurance_details;
  // Excel-faithful engine (Insurance Computation tab). Falls back to the
  // freedom-score estimate only when the CFP snapshot hasn't computed yet.
  const eng = (plan.computed?.cfp as { insurance?: InsuranceBlock } | undefined)?.insurance;
  const fs = plan.computed.freedom_score;

  // Life: cover the average of HLV & needs, plus outstanding loans; credit
  // existing cover AND disposable financial assets against it (Excel F30-F38).
  const lifeNeed = eng?.total_need_including_loans ?? fs?.required_life_cover ?? 0;
  const lifeExisting = eng?.existing_cover ?? ins.term_plan?.cover_amount ?? 0;
  const lifeAssets = eng?.investable_assets ?? 0;
  const lifeAdditional = eng?.additional_cover_required ?? Math.max(0, lifeNeed - lifeExisting - lifeAssets);
  const lifeCovered = lifeExisting + lifeAssets;
  const lifePct = lifeNeed > 0 ? Math.min(100, (lifeCovered / lifeNeed) * 100) : 0;

  // Medical (Excel G51-G65): higher of 50% gross income or family base +
  // separate senior-parent policies; credit existing health + floater cover.
  const medNeed = eng?.health?.required ?? fs?.required_medical_cover ?? 0;
  const medExisting =
    eng?.health?.existing_cover ??
    ((ins.health_insurance?.cover_amount ?? 0) + (ins.family_floater?.cover_amount ?? 0));
  const medAdditional = eng?.health?.additional_cover_required ?? Math.max(0, medNeed - medExisting);
  const medPct = medNeed > 0 ? Math.min(100, (medExisting / medNeed) * 100) : 0;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card title="Life cover adequacy" subtitle="Avg(HLV, needs) + loans − existing cover − disposable assets">
        <Bar pct={lifePct} />
        <div className="grid grid-cols-3 mt-3 text-xs gap-2">
          <Stat label="Total need" value={formatINR(lifeNeed, { compact: true })} />
          <Stat label="Covered (cover + assets)" value={formatINR(lifeCovered, { compact: true })} />
          <Stat label="Additional needed" value={formatINR(lifeAdditional, { compact: true })} accent={lifeAdditional > 0} />
        </div>
        {eng && (
          <div className="mt-3 pt-3 border-t border-zinc-100 grid grid-cols-2 gap-y-1 text-[11px] text-zinc-500">
            <span>Human Life Value</span><span className="text-right tabular-nums">{formatINR(eng.human_life_value ?? 0, { compact: true })}</span>
            <span>Needs-based corpus</span><span className="text-right tabular-nums">{formatINR(eng.needs_based_corpus ?? 0, { compact: true })}</span>
            <span>Existing cover</span><span className="text-right tabular-nums">{formatINR(lifeExisting, { compact: true })}</span>
            <span>Disposable assets credited</span><span className="text-right tabular-nums">{formatINR(lifeAssets, { compact: true })}</span>
          </div>
        )}
      </Card>

      <Card title="Medical cover adequacy" subtitle="Higher of 50% income or family base + senior-parent policies">
        <Bar pct={medPct} />
        <div className="grid grid-cols-3 mt-3 text-xs gap-2">
          <Stat label="Required" value={formatINR(medNeed, { compact: true })} />
          <Stat label="Existing" value={formatINR(medExisting, { compact: true })} />
          <Stat label="Additional needed" value={formatINR(medAdditional, { compact: true })} accent={medAdditional > 0} />
        </div>
        {eng?.health && (eng.health.senior_parent_cover ?? 0) > 0 && (
          <div className="mt-3 pt-3 border-t border-zinc-100 grid grid-cols-2 gap-y-1 text-[11px] text-zinc-500">
            <span>Family base cover</span><span className="text-right tabular-nums">{formatINR(eng.health.family_base ?? 0, { compact: true })}</span>
            <span>Senior-parent policies</span><span className="text-right tabular-nums">{formatINR(eng.health.senior_parent_cover ?? 0, { compact: true })}</span>
          </div>
        )}
      </Card>

      <div className="rounded-xl border border-zinc-200 bg-white p-5 lg:col-span-2">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">Existing policies</h3>
        <PolicyRow label="Term plan" b={ins.term_plan} />
        <PolicyRow label="Health insurance" b={ins.health_insurance} />
        <PolicyRow label="Family floater" b={ins.family_floater} />
        <PolicyRow label="ULIP / Endowment" b={ins.ulip_or_endowment} />
      </div>
    </div>
  );
}

function Card({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <header className="mb-3">
        <h3 className="text-sm font-medium text-zinc-700">{title}</h3>
        <p className="text-xs text-zinc-400">{subtitle}</p>
      </header>
      {children}
    </div>
  );
}

function Bar({ pct }: { pct: number }) {
  const color = pct >= 80 ? 'var(--color-accent)' : pct >= 50 ? '#a1a1aa' : '#52525b';
  return (
    <div className="space-y-1">
      <div className="h-2 rounded-full bg-zinc-100 overflow-hidden">
        <div className="h-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="text-[11px] text-zinc-500 text-right tabular-nums">{pct.toFixed(0)}% of required covered</div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <div className="text-zinc-400">{label}</div>
      <div className={`tabular-nums ${accent ? 'text-amber-700 font-medium' : 'text-zinc-800'}`}>{value}</div>
    </div>
  );
}

function PolicyRow({ label, b }: { label: string; b?: { company?: string | null; cover_amount?: number | null; annual_premium?: number | null } }) {
  const empty = !b?.company && !b?.cover_amount;
  return (
    <div className="flex items-center justify-between text-sm border-b border-zinc-100 py-1.5 last:border-0">
      <span className="text-zinc-700">{label}</span>
      {empty ? (
        <span className="text-xs text-zinc-400">—</span>
      ) : (
        <span className="text-xs text-zinc-700 tabular-nums">
          {b?.company ?? '—'} · cover {formatINR(b?.cover_amount ?? 0, { compact: true })} · premium{' '}
          {formatINR(b?.annual_premium ?? 0, { compact: true })}/yr
        </span>
      )}
    </div>
  );
}
