'use client';

import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip, ReferenceDot } from 'recharts';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { useState } from 'react';
import { MilestoneDrawer } from './MilestoneDrawer';

export function NetWorthChart({
  householdId,
  plan,
}: {
  householdId: string;
  plan: PlanState | null;
}) {
  const [pinIdx, setPinIdx] = useState<number | null>(null);

  const baseline = plan?.computed.net_worth_series ?? [];
  const planB = plan?.scenarios.find((s) => plan.active_scenario_ids.includes(s.id));
  const merged = baseline.map((d, i) => ({
    year: d.year,
    baseline: d.value,
    planB: planB ? planB.computed.net_worth_series[i]?.value ?? null : null,
  }));

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
                <stop offset="0%" stopColor="#6b8ee5" stopOpacity={0.45} />
                <stop offset="100%" stopColor="#6b8ee5" stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="grad-planb" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#a189d6" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#a189d6" stopOpacity={0.04} />
              </linearGradient>
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
            <Area type="monotone" dataKey="baseline" stroke="#6b8ee5" strokeWidth={2} fill="url(#grad-baseline)" dot={false} />
            {planB && <Area type="monotone" dataKey="planB" stroke="#a189d6" strokeWidth={2} fill="url(#grad-planb)" dot={false} />}
            {pins.map((p, i) => {
              const point = merged.find((m) => m.year === p.year);
              if (!point) return null;
              return (
                <ReferenceDot
                  key={i}
                  x={p.year}
                  y={point.baseline ?? 0}
                  r={6}
                  stroke="#6b8ee5"
                  strokeWidth={2}
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
