'use client';

import { useEffect, useState } from 'react';
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip, ReferenceDot } from 'recharts';
import { fetchPlan } from '@/lib/api';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

export function NetWorthChart({ householdId }: { householdId: string }) {
  const [plan, setPlan] = useState<PlanState | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = () => fetchPlan(householdId).then((p) => !cancelled && setPlan(p)).catch(() => undefined);
    tick();
    const id = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [householdId]);

  const baseline = plan?.computed.net_worth_series ?? [];
  const planB = plan?.scenarios.find((s) => plan.active_scenario_ids.includes(s.id));
  const merged = baseline.map((d, i) => ({
    year: d.year,
    baseline: d.value,
    planB: planB ? planB.computed.net_worth_series[i]?.value ?? null : null,
  }));

  return (
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
          {(plan?.computed.milestone_pins ?? []).map((p, i) => {
            const point = merged.find((m) => m.year === p.year);
            if (!point) return null;
            return (
              <ReferenceDot
                key={i}
                x={p.year}
                y={point.baseline ?? 0}
                r={5}
                stroke="#6b8ee5"
                strokeWidth={2}
                fill="#fff"
              />
            );
          })}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
