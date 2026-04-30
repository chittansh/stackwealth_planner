'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { useEffect, useState } from 'react';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type Tax = NonNullable<PlanState['computed']['tax']>;

export function TaxView({ householdId, plan }: { householdId: string; plan: PlanState | null }) {
  const cached = plan?.computed.tax;
  const [data, setData] = useState<Tax | null>(cached ?? null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (cached) setData(cached);
  }, [cached]);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`${BACKEND}/api/skill/tax/${householdId}`, { method: 'POST' });
      const j = await r.json();
      if ('error' in j) setErr(j.error);
      else setData(j);
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center flex flex-col items-center gap-2">
        <p>Tax view runs after a risk profile is set.</p>
        <button
          onClick={run}
          disabled={busy}
          className="text-xs px-3 py-1.5 rounded-md bg-zinc-900 text-white disabled:opacity-50"
        >
          {busy ? 'Running…' : 'Run tax review'}
        </button>
        {err && <p className="text-xs text-amber-600">{err}</p>}
      </div>
    );
  }

  const headroomPct = Math.max(0, Math.min(100, (data.ltcg_headroom_remaining / 125_000) * 100));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="rounded-xl border border-zinc-200 bg-white p-5 lg:col-span-1">
        <div className="text-[11px] uppercase tracking-wide text-zinc-400 mb-2">LTCG headroom (FY)</div>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tabular-nums">{formatINR(data.ltcg_headroom_remaining, { compact: true })}</span>
          <span className="text-zinc-400 text-xs">of ₹1.25 L</span>
        </div>
        <div className="mt-3 h-2 rounded-full bg-zinc-100 overflow-hidden">
          <div className="h-full bg-emerald-500" style={{ width: `${headroomPct}%` }} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
          <Stat label="Realized LTCG" value={formatINR(data.realized_ltcg_fy, { compact: true })} />
          <Stat label="Realized STCG" value={formatINR(data.realized_stcg_fy, { compact: true })} />
        </div>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-5 lg:col-span-2">
        <h3 className="text-sm font-medium text-zinc-700 mb-3">Harvest suggestions</h3>
        {data.gain_harvest_suggestions.length === 0 && data.loss_harvest_suggestions.length === 0 ? (
          <p className="text-xs text-zinc-500">
            Nothing to harvest yet. Add holdings with cost basis to see gain / loss harvesting opportunities.
          </p>
        ) : (
          <div className="flex flex-col gap-3 text-sm">
            {data.gain_harvest_suggestions.map((s, i) => (
              <Row
                key={`g${i}`}
                label={`Sell ${s.units.toFixed(1)} units · holding ${s.holding_id.slice(0, 6)}…`}
                tag="gain"
                value={`Gain ${formatINR(s.expected_gain, { compact: true })} · saves ${formatINR(s.tax_saved, { compact: true })}`}
              />
            ))}
            {data.loss_harvest_suggestions.map((s, i) => (
              <Row
                key={`l${i}`}
                label={`Sell ${s.units.toFixed(1)} units · holding ${s.holding_id.slice(0, 6)}…`}
                tag="loss"
                value={`Loss ${formatINR(s.expected_loss, { compact: true })} · offsets ${formatINR(s.tax_offset, { compact: true })}`}
              />
            ))}
          </div>
        )}

        {data.fee_vs_value_warnings.length > 0 && (
          <ul className="mt-4 text-xs text-amber-600 space-y-1">
            {data.fee_vs_value_warnings.map((w, i) => (
              <li key={i}>· {w}</li>
            ))}
          </ul>
        )}
        <div className="mt-4 text-xs text-zinc-500">
          Net post-tax delta: <span className="text-zinc-800 tabular-nums">{formatINR(data.net_post_tax_delta, { compact: true })}</span>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-zinc-50 rounded-md p-2">
      <div className="text-zinc-500">{label}</div>
      <div className="tabular-nums text-zinc-800">{value}</div>
    </div>
  );
}

function Row({ label, value, tag }: { label: string; value: string; tag: 'gain' | 'loss' }) {
  return (
    <div className="flex items-center justify-between border-b border-zinc-100 pb-1.5 last:border-0 last:pb-0">
      <div className="flex items-center gap-2">
        <span className={`px-1.5 py-0.5 text-[10px] uppercase rounded ${tag === 'gain' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
          {tag}
        </span>
        <span className="text-zinc-700">{label}</span>
      </div>
      <span className="text-xs text-zinc-600">{value}</span>
    </div>
  );
}
