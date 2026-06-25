'use client';

import { useEffect, useState } from 'react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts';

import type { PlanState, ScenariosSnapshot, ScenarioPath } from '@/types/plan-state';
import { fetchScenariosV2 } from '@/lib/api';
import { formatINR } from '@/lib/utils';
import { ComingSoonChip } from '@/components/common/ComingSoonChip';

/**
 * Scenarios tab — the brief's §8 Scenario Analysis on screen. Shows the
 * verdict + confidence, top-3 actions, the investable-surplus derivation, and
 * either a single optimised plan (on track) or Baseline / Easy / Aggressive
 * paths side-by-side with a comparison and "which path suits you".
 *
 * Reads `plan.computed.scenarios_v2`; fetches once if absent.
 */
export function ScenariosView({ plan }: { plan: PlanState | null }) {
  const persisted = (plan?.computed?.scenarios_v2 ?? null) as ScenariosSnapshot | null;
  const [local, setLocal] = useState<ScenariosSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [whatif, setWhatif] = useState<ScenariosSnapshot | null>(null); // RM override result
  const [running, setRunning] = useState(false);
  const id = plan?.household_id;
  const hasCfp = !!plan?.computed?.cfp;

  useEffect(() => {
    if (persisted || local || !id || !hasCfp || loading) return;
    setLoading(true);
    fetchScenariosV2(id)
      .then((s) => setLocal(s as ScenariosSnapshot))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id, hasCfp, persisted, local, loading]);

  const base = persisted ?? local;
  const s = whatif ?? base;

  const applyOverrides = (ov: Record<string, unknown>) => {
    if (!id) return;
    setRunning(true);
    fetchScenariosV2(id, ov)
      .then((r) => setWhatif(r as ScenariosSnapshot))
      .catch(() => {})
      .finally(() => setRunning(false));
  };

  if (!plan) return null;
  if (!hasCfp) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Add income and goals first — the scenario engine needs a baseline to compare against.
      </div>
    );
  }
  if (loading && !s) {
    return (
      <div className="rounded-xl border border-dashed border-[color:var(--color-accent,#5f7d56)]/40 p-10 text-sm text-zinc-500 text-center">
        Running the scenario engine…
      </div>
    );
  }
  if (!s) return null;

  const conf = s.verdict?.confidence ?? 'Medium';
  const confTone =
    conf.toLowerCase().includes('high')
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : conf.toLowerCase().includes('medium')
      ? 'bg-amber-50 text-amber-700 border-amber-200'
      : 'bg-rose-50 text-rose-700 border-rose-200';

  const paths = (s.scenarios ?? []).filter((p) => p.key !== 'baseline');

  return (
    <div className="flex flex-col gap-5">
      {/* WIP marker — scenarios are still being refined with the SW team */}
      <div className="flex justify-end -mb-2">
        <ComingSoonChip />
      </div>

      {/* What-if banner */}
      {whatif && (
        <div className="flex items-center justify-between rounded-lg border border-sky-200 bg-sky-50 px-4 py-2.5 text-xs">
          <span className="text-sky-800">Showing a <strong>what-if</strong> with your additional inputs applied. The saved plan is unchanged.</span>
          <button className="text-sky-700 underline" onClick={() => setWhatif(null)}>Reset to baseline</button>
        </div>
      )}

      {/* Verdict */}
      <div className="rounded-xl border border-[color:var(--color-accent,#5f7d56)]/30 bg-[color:var(--color-accent,#5f7d56)]/[0.05] p-5">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] uppercase tracking-wide font-semibold text-[color:var(--color-accent,#5f7d56)]">
            The Verdict
          </span>
          <span className={`text-[10px] uppercase tracking-wide border rounded-full px-2 py-0.5 ${confTone}`}>
            Confidence: {conf}
          </span>
        </div>
        <p className="text-base font-medium text-zinc-800 leading-snug">{s.verdict?.text}</p>
      </div>

      {/* Surplus → SIP feasibility (goals + retirement explicit) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Investable surplus" value={`${formatINR(s.surplus?.investable_surplus ?? 0)}/mo`} />
        <Stat label="Goal SIP needed" value={`${formatINR(s.goal_sip_needed ?? 0)}/mo`} />
        <Stat label="Retirement SIP needed" value={`${formatINR(s.retirement_sip_needed ?? 0)}/mo`} />
        <Stat
          label="Gap vs total SIP"
          value={`${formatINR(Math.abs((s.surplus?.investable_surplus ?? 0) - (s.total_sip_needed ?? 0)))}/mo`}
          accent={(s.surplus?.investable_surplus ?? 0) >= (s.total_sip_needed ?? 0) ? 'good' : 'bad'}
        />
      </div>

      {/* RM additional inputs */}
      <RMInputs plan={plan} onApply={applyOverrides} running={running} />

      {/* Top 3 actions */}
      {s.top_actions?.length > 0 && (
        <div className="rounded-xl border border-zinc-200 bg-white p-5">
          <h3 className="text-sm font-medium text-zinc-700 mb-2">Three things to do, whichever path you choose</h3>
          <ol className="list-decimal ml-5 text-sm text-zinc-700 flex flex-col gap-1.5">
            {s.top_actions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ol>
        </div>
      )}

      {/* Single plan (on track) OR Easy/Aggressive paths */}
      {s.achievable && s.single_plan ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-5">
          <h3 className="text-sm font-medium text-emerald-800 mb-1">Your single optimised plan</h3>
          <p className="text-sm text-zinc-700">{s.single_plan.headline}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
            {paths.map((p) => (
              <PathCard key={p.key} path={p} />
            ))}
          </div>
          {s.comparison && s.comparison.length > 0 && <ComparisonTable s={s} />}
          {s.which_path && s.which_path.length > 0 && (
            <div className="rounded-xl border border-zinc-200 bg-white p-5">
              <h3 className="text-sm font-medium text-zinc-700 mb-2">Which path is right for you?</h3>
              <div className="flex flex-col gap-2 text-sm text-zinc-700">
                {s.which_path.map((w) => (
                  <p key={w.path}>
                    <span className="font-medium text-zinc-900">{w.path}.</span> {w.suits}
                  </p>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RMInputs({
  plan,
  onApply,
  running,
}: {
  plan: PlanState;
  onApply: (ov: Record<string, unknown>) => void;
  running: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [lumpAmt, setLumpAmt] = useState('');
  const [lumpYr, setLumpYr] = useState('');
  const [incomePct, setIncomePct] = useState('');
  const [stepUp, setStepUp] = useState('');
  const [goalOv, setGoalOv] = useState<Record<string, { delay_years?: string; reduce_pct?: string }>>({});

  // Flexible goals only (the engine ignores delays on child/retirement anyway).
  const flexGoals = (plan.financial_goals || []).filter(
    (g) => !['child_education', 'child_marriage', 'retirement'].includes((g.kind as string) || ''),
  );

  const submit = () => {
    const overrides: Record<string, unknown> = {};
    if (lumpAmt && lumpYr) {
      overrides.lumpsum_amount = Number(lumpAmt);
      overrides.lumpsum_year = Number(lumpYr);
    }
    if (incomePct) overrides.income_increase_pct = Number(incomePct);
    if (stepUp) overrides.step_up_pct = Number(stepUp);
    const go: Record<string, unknown> = {};
    for (const [gid, v] of Object.entries(goalOv)) {
      const o: Record<string, number> = {};
      if (v.delay_years) o.delay_years = Number(v.delay_years);
      if (v.reduce_pct) o.reduce_pct = Number(v.reduce_pct);
      if (Object.keys(o).length) go[gid] = o;
    }
    if (Object.keys(go).length) overrides.goal_overrides = go;
    onApply(overrides);
  };

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <button
        className="flex items-center justify-between w-full text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <h3 className="text-sm font-medium text-zinc-700">Adjust the scenario — additional inputs</h3>
        <span className="text-xs text-zinc-400">{open ? '−' : '+'}</span>
      </button>
      {!open && (
        <p className="text-[11px] text-zinc-400 mt-1">
          Add an expected lumpsum, an income lift, a step-up rate, or nudge specific goals — the scenarios re-run on your inputs.
        </p>
      )}
      {open && (
        <div className="mt-3 flex flex-col gap-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Expected lumpsum (₹)" placeholder="e.g. 3000000" value={lumpAmt} onChange={setLumpAmt} />
            <Field label="…in year" placeholder="e.g. 2028" value={lumpYr} onChange={setLumpYr} />
            <Field label="Income increase (%)" placeholder="e.g. 10" value={incomePct} onChange={setIncomePct} />
            <Field label="SIP step-up (%/yr)" placeholder="e.g. 12" value={stepUp} onChange={setStepUp} />
          </div>
          {flexGoals.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1.5">Per-goal nudges (flexible goals)</div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-zinc-500 border-b border-zinc-100">
                    <th className="py-1 font-medium">Goal</th>
                    <th className="py-1 font-medium">Delay (yrs, ≤5)</th>
                    <th className="py-1 font-medium">Reduce (%, ≤30)</th>
                  </tr>
                </thead>
                <tbody>
                  {flexGoals.map((g) => (
                    <tr key={g.id} className="border-b border-zinc-100 last:border-0">
                      <td className="py-1 text-zinc-700">{g.goal_name}</td>
                      <td className="py-1">
                        <input
                          className="w-16 border border-zinc-200 rounded px-1.5 py-0.5 text-xs"
                          value={goalOv[g.id]?.delay_years ?? ''}
                          onChange={(e) => setGoalOv((p) => ({ ...p, [g.id]: { ...p[g.id], delay_years: e.target.value } }))}
                        />
                      </td>
                      <td className="py-1">
                        <input
                          className="w-16 border border-zinc-200 rounded px-1.5 py-0.5 text-xs"
                          value={goalOv[g.id]?.reduce_pct ?? ''}
                          onChange={(e) => setGoalOv((p) => ({ ...p, [g.id]: { ...p[g.id], reduce_pct: e.target.value } }))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div>
            <button
              onClick={submit}
              disabled={running}
              className="text-xs font-medium bg-[color:var(--color-accent,#5f7d56)] text-white rounded-md px-4 py-2 disabled:opacity-50"
            >
              {running ? 'Re-running…' : 'Apply & re-run scenarios'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, placeholder, value, onChange }: { label: string; placeholder: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <input
        className="border border-zinc-200 rounded-md px-2.5 py-1.5 text-sm"
        inputMode="numeric"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function PathCard({ path }: { path: ScenarioPath }) {
  // Path 2 is the "stretch" path — give it the accent treatment.
  const accent = path.key === 'path2';
  const corpusPct = path.corpus_required > 0 ? Math.round((path.retirement_corpus / path.corpus_required) * 100) : 100;
  return (
    <div
      className={`rounded-xl border p-5 flex flex-col gap-3 ${
        accent ? 'border-[color:var(--color-accent,#5f7d56)]/40 bg-[color:var(--color-accent,#5f7d56)]/[0.04]' : 'border-zinc-200 bg-white'
      }`}
    >
      {/* Block 1 — headline */}
      <div>
        <h3 className="text-sm font-semibold text-zinc-800">{path.name}</h3>
        <p className="text-xs text-zinc-600 mt-1">{path.headline}</p>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <Mini label="Monthly SIP (start)" value={`${formatINR(path.monthly_sip)}/mo`} />
        <Mini label="Retire at" value={`${path.retirement_age}`} />
        <Mini label="Retirement corpus" value={formatINR(path.retirement_corpus, { compact: true })} />
        <Mini label="Goals funded" value={`${path.goals_met_pct}%`} />
      </div>

      {/* Block 2 — levers pulled with magnitudes */}
      <div>
        <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Levers pulled</div>
        <ul className="text-xs text-zinc-700 flex flex-col gap-1.5">
          {path.levers.map((l, i) => (
            <li key={i} className={`flex gap-1.5 ${l.lever8 ? 'flex-col' : ''}`}>
              {l.lever8 ? (
                <div className="rounded-md border border-amber-300 bg-amber-50 px-2.5 py-2 text-amber-900">
                  {l.text}
                </div>
              ) : (
                <>
                  <span className="text-[color:var(--color-accent,#5f7d56)]">•</span>
                  <span>{l.text}</span>
                </>
              )}
            </li>
          ))}
        </ul>
      </div>

      {/* Block 3 — what this funds (structural anchor) */}
      {path.outcomes && path.outcomes.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">What this funds</div>
          <table className="w-full text-[11px]">
            <tbody>
              {path.outcomes.map((o) => (
                <tr key={o.goal} className="border-b border-zinc-100 last:border-0 align-top">
                  <td className="py-1 text-zinc-700 whitespace-nowrap pr-2">{o.goal}</td>
                  <td className="py-1 text-zinc-700">{o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Block 4 — what it asks of you */}
      <div>
        <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">What it asks of you</div>
        <p className="text-[11px] text-zinc-600 leading-snug">{path.trade_off}</p>
      </div>

      {path.advisor_note && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-900">
          {path.advisor_note}
        </div>
      )}

      {/* Block 5 — small wealth-trajectory chart */}
      {path.net_worth_series && path.net_worth_series.length > 1 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
            Wealth trajectory · corpus {corpusPct}% of target
          </div>
          <div className="h-[90px] w-full">
            <ResponsiveContainer>
              <AreaChart data={path.net_worth_series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id={`sg-${path.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#5f7d56" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#5f7d56" stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="year" hide />
                <Tooltip
                  formatter={(v: number) => formatINR(v, { compact: true })}
                  labelFormatter={(l) => `Year ${l}`}
                  contentStyle={{ borderRadius: 8, border: '1px solid #e4e4e7', fontSize: 11 }}
                />
                <Area type="monotone" dataKey="value" stroke="#5f7d56" strokeWidth={1.5} fill={`url(#sg-${path.key})`} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

function ComparisonTable({ s }: { s: ScenariosSnapshot }) {
  const fmt = (v: unknown, kind: string) => {
    if (v === null || v === undefined) return '—';
    if (kind === 'money') return formatINR(Number(v), { compact: true });
    if (kind === 'pct') return `${v}%`;
    if (kind === 'age') return `Age ${v}`;
    return String(v);
  };
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 overflow-x-auto">
      <h3 className="text-sm font-medium text-zinc-700 mb-3">Side-by-side comparison</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-zinc-500 border-b border-zinc-100">
            <th className="py-1.5 font-medium">Metric</th>
            <th className="py-1.5 font-medium">Baseline</th>
            <th className="py-1.5 font-medium">Path 1 · Reducing</th>
            <th className="py-1.5 font-medium">Path 2 · Stretching</th>
            <th className="py-1.5 font-medium">Path 3 · Balanced</th>
          </tr>
        </thead>
        <tbody>
          {(s.comparison ?? []).map((r) => (
            <tr key={r.metric} className="border-b border-zinc-100 last:border-0 align-top">
              <td className="py-1.5 text-zinc-700">{r.metric}</td>
              <td className="py-1.5 text-zinc-500">{fmt(r.baseline, r.kind)}</td>
              <td className="py-1.5 text-zinc-700">{fmt(r.path1, r.kind)}</td>
              <td className="py-1.5 text-zinc-700">{fmt(r.path2, r.kind)}</td>
              <td className="py-1.5 text-zinc-700">{fmt(r.path3, r.kind)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: 'good' | 'bad' }) {
  const cls = accent === 'bad' ? 'text-rose-700' : accent === 'good' ? 'text-emerald-700' : 'text-zinc-800';
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-zinc-400">{label}</div>
      <div className={`text-base font-semibold tabular-nums mt-0.5 ${cls}`}>{value}</div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <span className="tabular-nums font-medium text-zinc-800">{value}</span>
    </div>
  );
}
