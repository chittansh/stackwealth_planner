'use client';

import type { PlanState } from '@/types/plan-state';
import { useState, useMemo } from 'react';
import { formatINR } from '@/lib/utils';
import { firePlanChanged } from '@/lib/prompt';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

export function Scenarios({ householdId, plan }: { householdId: string; plan: PlanState | null }) {
  const [sip, setSip] = useState(0);          // ₹/mo delta
  const [retire, setRetire] = useState(0);    // years delta
  const [shock, setShock] = useState(0);      // % drawdown (0..40)
  const [busy, setBusy] = useState(false);

  const baseline = plan?.computed.headline_amount_at_horizon ?? 0;
  const planB = plan?.scenarios.find((s) => plan.active_scenario_ids.includes(s.id));

  const dirty = sip !== 0 || retire !== 0 || shock !== 0;

  const personId = plan?.assumptions.persons[0]?.id;

  const pinScenario = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      const ops: { path: string; op: 'set' | 'add' | 'remove'; value?: unknown; row?: unknown; id?: string }[] = [];
      if (sip !== 0) {
        ops.push({
          path: 'monthly_investments.mutual_fund_sip',
          op: 'set',
          value: Math.max(0, (plan.monthly_investments.mutual_fund_sip ?? 0) + sip),
        });
      }
      if (retire !== 0 && personId) {
        const cur = plan.assumptions.persons[0]?.retirement_age ?? plan.personal_details.retirement_age_target ?? 60;
        ops.push({
          path: `assumptions.persons.0.retirement_age`,
          op: 'set',
          value: cur + retire,
        });
      }
      if (shock !== 0) {
        ops.push({
          path: 'assumptions.growth.investment',
          op: 'set',
          value: Math.max(-0.4, plan.assumptions.growth.investment - shock / 100 / 5),
        });
      }
      const label = labelFor({ sip, retire, shock });
      await fetch(`${BACKEND}/api/scenario/${householdId}/pin`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ label, mutation: { ops } }),
      });
      firePlanChanged();
    } finally {
      setBusy(false);
    }
  };

  const runMC = async () => {
    setBusy(true);
    try {
      await fetch(`${BACKEND}/api/skill/montecarlo/${householdId}`, { method: 'POST' });
      firePlanChanged();
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    try {
      await fetch(`${BACKEND}/api/scenario/${householdId}/clear`, { method: 'POST' });
      firePlanChanged();
    } finally {
      setBusy(false);
      setSip(0);
      setRetire(0);
      setShock(0);
    }
  };

  const projectedDelta = useMemo(() => {
    if (!planB) return 0;
    return planB.computed.headline_amount_at_horizon - baseline;
  }, [baseline, planB]);

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <header className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-medium text-zinc-700">Scenarios</h3>
          <p className="text-xs text-zinc-400">Drag a slider, pin as Plan B, watch the dial move.</p>
        </div>
        <div className="flex items-center gap-2">
          {planB && (
            <span className="text-xs text-zinc-500">
              Plan B Δ{' '}
              <span style={{ color: projectedDelta >= 0 ? 'var(--color-accent)' : '#52525b' }}>
                {projectedDelta >= 0 ? '+' : ''}
                {formatINR(projectedDelta, { compact: true })}
              </span>
            </span>
          )}
          <button
            onClick={runMC}
            disabled={busy}
            className="text-xs px-3 py-1.5 rounded-md border border-zinc-200 hover:bg-zinc-50 disabled:opacity-50"
          >
            Run Monte Carlo
          </button>
          <button
            onClick={clear}
            disabled={busy || (!planB && !dirty)}
            className="text-xs px-3 py-1.5 rounded-md border border-zinc-200 hover:bg-zinc-50 disabled:opacity-50"
          >
            Clear
          </button>
          <button
            onClick={pinScenario}
            disabled={busy || !dirty}
            className="text-xs px-3 py-1.5 rounded-md bg-zinc-900 text-white disabled:opacity-50"
          >
            Pin as Plan B
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Slider
          label="Monthly SIP delta"
          value={sip}
          min={-50_000}
          max={50_000}
          step={1_000}
          format={(n) => `${n >= 0 ? '+' : ''}${formatINR(n, { compact: true })}/mo`}
          onChange={setSip}
        />
        <Slider
          label="Retirement age delta"
          value={retire}
          min={-10}
          max={10}
          step={1}
          format={(n) => `${n >= 0 ? '+' : ''}${n} yr`}
          onChange={setRetire}
        />
        <Slider
          label="Equity drawdown shock"
          value={shock}
          min={0}
          max={40}
          step={1}
          format={(n) => `−${n}%`}
          onChange={setShock}
        />
      </div>
    </section>
  );
}

function labelFor({ sip, retire, shock }: { sip: number; retire: number; shock: number }) {
  const parts: string[] = [];
  if (sip !== 0) parts.push(`SIP ${sip >= 0 ? '+' : ''}${Math.round(sip / 1000)}k/mo`);
  if (retire !== 0) parts.push(`Retire ${retire >= 0 ? '+' : ''}${retire}y`);
  if (shock !== 0) parts.push(`Equity −${shock}%`);
  return parts.join(' · ') || 'Plan B';
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (n: number) => string;
  onChange: (n: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-zinc-500">{label}</span>
        <span className="text-xs tabular-nums text-zinc-800">{format(value)}</span>
      </div>
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[color:var(--color-accent)]"
      />
    </div>
  );
}
