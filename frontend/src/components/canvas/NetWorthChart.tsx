'use client';

import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip, ReferenceDot } from 'recharts';
import type { PlanState, SuggestionsSnapshot } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { useEffect, useState } from 'react';
import { fetchSuggestions } from '@/lib/api';
import { MilestoneDrawer } from './MilestoneDrawer';

export function NetWorthChart({
  householdId,
  plan,
}: {
  householdId: string;
  plan: PlanState | null;
}) {
  const [pinIdx, setPinIdx] = useState<number | null>(null);

  // Suggested-plan overlay — read the persisted snapshot, else fetch once.
  const persistedSug = (plan?.computed?.suggestions ?? null) as SuggestionsSnapshot | null;
  const [localSug, setLocalSug] = useState<SuggestionsSnapshot | null>(null);
  const sug = persistedSug ?? localSug;
  const hasCfp = !!plan?.computed?.cfp;
  useEffect(() => {
    if (persistedSug || localSug || !householdId || !hasCfp) return;
    fetchSuggestions(householdId)
      .then((s) => setLocalSug(s as SuggestionsSnapshot))
      .catch(() => {});
  }, [householdId, hasCfp, persistedSug, localSug]);
  const suggestedSeries = sug?.suggested?.net_worth_series ?? [];
  const recDelta = sug?.recommended?.impact?.headline_delta ?? 0;

  const baseline = plan?.computed.net_worth_series ?? [];
  // One series per active scenario. The chips already render every active
  // scenario; the chart needs to do the same instead of picking just the
  // first via .find() (which is what hid Plan B / Plan C from the canvas).
  const activeScenarios = (plan?.scenarios ?? []).filter((s) =>
    (plan?.active_scenario_ids ?? []).includes(s.id),
  );
  const merged = baseline.map((d, i) => {
    const row: Record<string, number | null> = { year: d.year, baseline: d.value };
    activeScenarios.forEach((s, idx) => {
      row[`scenario_${idx}`] = s.computed.net_worth_series[i]?.value ?? null;
    });
    if (suggestedSeries.length) {
      row.suggested = suggestedSeries[i]?.value ?? null;
    }
    return row;
  });

  // Stable palette for up to 4 pinned scenarios. Index 0 is the matcha green
  // already used as "Plan B" so pre-existing screenshots keep their colour.
  const SCENARIO_COLOURS = ['#87a17e', '#7e9aa1', '#a18a7e', '#9e7ea1'];

  const pins = plan?.computed.milestone_pins ?? [];
  const mc = plan?.computed.monte_carlo;

  if (merged.length === 0) {
    return (
      <div className="w-full h-[320px] rounded-xl border border-dashed border-zinc-200 grid place-items-center text-sm text-zinc-500">
        Drop a statement, paste a note, or click + to add income — your projection appears here.
      </div>
    );
  }

  return (
    <>
      <div className="w-full h-[320px]">
        <ResponsiveContainer>
          <AreaChart data={merged} margin={{ top: 10, right: 24, bottom: 8, left: 0 }}>
            <defs>
              <linearGradient id="grad-baseline" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#52525b" stopOpacity={0.18} />
                <stop offset="100%" stopColor="#52525b" stopOpacity={0.02} />
              </linearGradient>
              {SCENARIO_COLOURS.map((c, idx) => (
                <linearGradient key={idx} id={`grad-scenario-${idx}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={c} stopOpacity={0.32} />
                  <stop offset="100%" stopColor={c} stopOpacity={0.03} />
                </linearGradient>
              ))}
            </defs>
            <XAxis
              dataKey="year"
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              tick={{ fontSize: 11, fill: '#a1a1aa' }}
            />
            <YAxis
              tickFormatter={(v: number) => formatINR(v, { compact: true }).replace('₹', '')}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: '#a1a1aa' }}
              width={64}
            />
            <Tooltip
              formatter={(v: number) => formatINR(v, { compact: true })}
              contentStyle={{ borderRadius: 8, border: '1px solid #e4e4e7', fontSize: 12 }}
            />
            <Area type="monotone" dataKey="baseline" stroke="#52525b" strokeWidth={1.5} fill="url(#grad-baseline)" dot={false} />
            {suggestedSeries.length > 0 && (
              <Area
                type="monotone"
                dataKey="suggested"
                stroke="#5f7d56"
                strokeWidth={1.5}
                strokeDasharray="5 3"
                fill="none"
                dot={false}
                name="Suggested"
              />
            )}
            {activeScenarios.map((_, idx) => {
              const colour = SCENARIO_COLOURS[idx % SCENARIO_COLOURS.length];
              return (
                <Area
                  key={idx}
                  type="monotone"
                  dataKey={`scenario_${idx}`}
                  stroke={colour}
                  strokeWidth={1.5}
                  fill={`url(#grad-scenario-${idx % SCENARIO_COLOURS.length})`}
                  dot={false}
                />
              );
            })}
            {pins.map((p, i) => {
              const point = merged.find((m) => m.year === p.year);
              if (!point) return null;
              return (
                <ReferenceDot
                  key={i}
                  x={p.year}
                  y={point.baseline ?? 0}
                  r={5}
                  stroke="#52525b"
                  strokeWidth={1.5}
                  fill="#fff"
                  onClick={() => setPinIdx(i)}
                  style={{ cursor: 'pointer' }}
                />
              );
            })}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {mc && (
        <div className="mt-2 text-xs text-zinc-500">
          MC ({mc.paths_count} paths) · P10 age {mc.p10_freedom_age} · P50 {mc.p50_freedom_age} · P90 {mc.p90_freedom_age}
        </div>
      )}
      {sug?.has_gaps && suggestedSeries.length > 0 && (
        <div className="mt-2 flex items-center justify-between rounded-lg border border-[color:var(--color-accent,#5f7d56)]/30 bg-[color:var(--color-accent,#5f7d56)]/[0.05] px-3 py-2 text-xs">
          <span className="text-zinc-600">
            <span className="font-medium text-[color:var(--color-accent,#5f7d56)]">Suggested plan</span>{' '}
            (dashed): {sug.recommended?.summary}
          </span>
          {recDelta !== 0 && (
            <span className="tabular-nums font-semibold text-emerald-700 whitespace-nowrap ml-3">
              {recDelta >= 0 ? '+' : ''}
              {formatINR(recDelta, { compact: true })} at horizon
            </span>
          )}
        </div>
      )}
      {pinIdx !== null && pins[pinIdx] && (
        <MilestoneDrawer
          householdId={householdId}
          plan={plan!}
          pin={pins[pinIdx]}
          onClose={() => setPinIdx(null)}
        />
      )}
    </>
  );
}
