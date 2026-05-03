'use client';

import type { PlanState } from '@/types/plan-state';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

export function ScenarioChips({ plan }: { plan: PlanState | null }) {
  if (!plan || plan.scenarios.length === 0) return null;

  const toggle = async (id: string) => {
    const isActive = plan.active_scenario_ids.includes(id);
    await fetch(`${BACKEND}/api/scenario/${plan.household_id}/toggle`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ id, active: !isActive }),
    });
  };

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Chip label="Baseline" color="#52525b" active />
      {plan.scenarios.map((s, i) => {
        const active = plan.active_scenario_ids.includes(s.id);
        return (
          <Chip
            key={s.id}
            label={s.label || `Scenario ${String.fromCharCode(65 + i)}`}
            color="#87a17e"
            active={active}
            onClick={() => toggle(s.id)}
          />
        );
      })}
    </div>
  );
}

function Chip({
  label,
  color,
  active,
  onClick,
}: {
  label: string;
  color: string;
  active: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-md border transition ${
        active
          ? 'border-zinc-200 text-zinc-800 bg-white'
          : 'border-zinc-100 text-zinc-400 bg-zinc-50 line-through'
      }`}
    >
      <span className="w-2 h-2 rounded-full" style={{ background: color, opacity: active ? 1 : 0.4 }} />
      {label}
    </button>
  );
}
