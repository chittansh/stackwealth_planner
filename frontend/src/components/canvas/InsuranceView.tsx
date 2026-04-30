'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function InsuranceView({ plan }: { plan: PlanState | null }) {
  if (!plan) return null;
  const fs = plan.computed.freedom_score;
  const ins = plan.insurance_details;
  const lifeCover = ins.term_plan?.cover_amount ?? 0;
  const medCover = ins.health_insurance?.cover_amount ?? 0;
  const reqLife = fs?.required_life_cover ?? 0;
  const reqMed = fs?.required_medical_cover ?? 0;

  const lifePct = reqLife > 0 ? Math.min(100, (lifeCover / reqLife) * 100) : 0;
  const medPct = reqMed > 0 ? Math.min(100, (medCover / reqMed) * 100) : 0;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card title="Life cover adequacy" subtitle={`Metro multiplier ${(fs?.city_cover_multiplier ?? 1).toFixed(2)}`}>
        <Bar label="Actual" value={lifeCover} required={reqLife} pct={lifePct} />
        <Meta required={reqLife} actual={lifeCover} period="lifetime" />
      </Card>
      <Card title="Medical cover adequacy" subtitle="Family floater preferred">
        <Bar label="Actual" value={medCover} required={reqMed} pct={medPct} />
        <Meta required={reqMed} actual={medCover} period="annual" />
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

function Bar({ label, value, required, pct }: { label: string; value: number; required: number; pct: number }) {
  const _ = label;
  void _;
  void value;
  void required;
  return (
    <div className="space-y-1">
      <div className="h-3 rounded-full bg-zinc-100 overflow-hidden">
        <div className={`h-full ${pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-rose-500'}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="text-[11px] text-zinc-500 text-right tabular-nums">{pct.toFixed(0)}% of required</div>
    </div>
  );
}

function Meta({ required, actual, period }: { required: number; actual: number; period: string }) {
  return (
    <div className="grid grid-cols-2 mt-3 text-xs">
      <div>
        <div className="text-zinc-400">Actual ({period})</div>
        <div className="tabular-nums text-zinc-800">{formatINR(actual, { compact: true })}</div>
      </div>
      <div className="text-right">
        <div className="text-zinc-400">Required</div>
        <div className="tabular-nums text-zinc-800">{formatINR(required, { compact: true })}</div>
      </div>
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
