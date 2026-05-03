'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import type { MilestonePin, PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { planSet } from '@/lib/api';
import { firePlanChanged } from '@/lib/prompt';

export function MilestoneDrawer({
  householdId,
  plan,
  pin,
  onClose,
}: {
  householdId: string;
  plan: PlanState;
  pin: MilestonePin;
  onClose: () => void;
}) {
  const goal = plan.financial_goals.find((g) => g.id === pin.goal_id);
  const [year, setYear] = useState(pin.year);
  const [amount, setAmount] = useState(goal?.target_amount ?? goal?.today_cost ?? 0);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!goal) return;
    setBusy(true);
    const idx = plan.financial_goals.findIndex((g) => g.id === goal.id);
    if (idx < 0) {
      setBusy(false);
      return;
    }
    await planSet(householdId, `financial_goals.${idx}.target_year`, year);
    await planSet(householdId, `financial_goals.${idx}.target_amount`, Number(amount));
    firePlanChanged();
    setBusy(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <aside className="w-[360px] bg-white border-l border-zinc-200 p-5 flex flex-col gap-4">
        <header className="flex items-center justify-between">
          <h3 className="text-sm font-medium">{pin.label}</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-700">
            <X size={16} />
          </button>
        </header>
        <div className="flex flex-col gap-3 text-sm">
          <Field label="Type" value={pin.type.replace(/_/g, ' ')} readOnly />
          <Field label="Year" value={year} type="number" onChange={(v) => setYear(Number(v))} />
          <Field
            label="Target amount"
            value={amount}
            type="number"
            onChange={(v) => setAmount(Number(v))}
            help={`≈ ${formatINR(Number(amount), { compact: true })}`}
          />
          {goal && (
            <div className="text-xs text-zinc-500">
              Priority: {goal.priority ?? 'important'} · Horizon: {goal.horizon_years ?? '—'} yr
            </div>
          )}
        </div>
        <div className="mt-auto flex justify-end gap-2">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded-md border border-zinc-200">
            Cancel
          </button>
          <button
            onClick={save}
            disabled={busy}
            className="text-xs px-3 py-1.5 rounded-md bg-zinc-900 text-white disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </aside>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  help,
  readOnly,
}: {
  label: string;
  value: string | number;
  onChange?: (v: string) => void;
  type?: 'text' | 'number';
  help?: string;
  readOnly?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-zinc-500">{label}</span>
      <input
        type={type}
        value={value}
        readOnly={readOnly}
        onChange={(e) => onChange?.(e.target.value)}
        className="border border-zinc-200 rounded-md px-2 py-1.5 text-sm tabular-nums focus:outline-none focus:border-zinc-400 bg-white read-only:bg-zinc-50"
      />
      {help && <span className="text-[11px] text-zinc-400">{help}</span>}
    </label>
  );
}
