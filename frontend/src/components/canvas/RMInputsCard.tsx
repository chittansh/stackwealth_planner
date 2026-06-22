'use client';

import { useState } from 'react';
import type { PlanState, LumpsumEvent } from '@/types/plan-state';
import { planSet } from '@/lib/api';
import { firePlanChanged } from '@/lib/prompt';
import { Plus, X } from 'lucide-react';

/**
 * RM-entered planning inputs that aren't derivable from the standard input tabs
 * but materially change the projection:
 *   • Business retirement age — the year business income runs to (often later
 *     than salaried retirement). Drives the YoY business-income cut-off.
 *   • Dependent senior parents — each adds a separate ~₹20L health policy.
 *   • Manual lumpsums — one-off cash events (bonus, reverse mortgage, asset
 *     sale, one-off medical) folded into the cashflow's Lumpsum column.
 *
 * Persists straight to the plan via planSet, then fires a refresh.
 */
export function RMInputsCard({ plan }: { plan: PlanState }) {
  const id = plan.household_id;
  const pd = plan.personal_details;

  const [bizAge, setBizAge] = useState(pd.business_retirement_age?.toString() ?? '');
  const [parents, setParents] = useState(pd.dependent_senior_parents?.toString() ?? '');
  const [events, setEvents] = useState<LumpsumEvent[]>(plan.assumptions.lumpsum_events ?? []);
  const [status, setStatus] = useState<'' | 'saving' | 'saved'>('');

  const save = async (path: string, value: unknown) => {
    setStatus('saving');
    await planSet(id, path, value);
    firePlanChanged();
    setStatus('saved');
    setTimeout(() => setStatus(''), 1500);
  };

  const saveScalar = (path: string, raw: string) => {
    const v = raw.trim() === '' ? null : Number(raw);
    if (raw.trim() !== '' && Number.isNaN(v)) return;
    save(path, v);
  };

  const updateEvent = (i: number, patch: Partial<LumpsumEvent>) =>
    setEvents((es) => es.map((e, j) => (j === i ? { ...e, ...patch } : e)));

  const addEvent = () =>
    setEvents((es) => [
      ...es,
      { id: crypto.randomUUID(), year: new Date().getFullYear() + 1, amount: 0, label: '' },
    ]);

  const removeEvent = (i: number) => setEvents((es) => es.filter((_, j) => j !== i));

  const saveEvents = () => {
    const clean = events
      .filter((e) => e.year && e.amount)
      .map((e) => ({ ...e, year: Number(e.year), amount: Number(e.amount) }));
    save('assumptions.lumpsum_events', clean);
  };

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <header className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-medium text-zinc-700">Planner inputs (RM)</h3>
        {status && (
          <span className={`text-[11px] ${status === 'saved' ? 'text-emerald-600' : 'text-zinc-400'}`}>
            {status === 'saving' ? 'Saving…' : 'Saved ✓'}
          </span>
        )}
      </header>
      <p className="text-[11px] text-zinc-400 mb-4">
        RM judgement that isn&apos;t in the input sheets but moves the projection — these persist to the plan and
        re-run cashflow, retirement, and insurance.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
        <Field
          label="Business retirement age"
          hint="Age business income runs to (blank = same as retirement age)"
          value={bizAge}
          onChange={setBizAge}
          onCommit={() => saveScalar('personal_details.business_retirement_age', bizAge)}
          placeholder="e.g. 60"
        />
        <Field
          label="Dependent senior parents"
          hint="Each adds a separate ~₹20L health policy"
          value={parents}
          onChange={setParents}
          onCommit={() => saveScalar('personal_details.dependent_senior_parents', parents)}
          placeholder="e.g. 1"
        />
      </div>

      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] uppercase tracking-wide text-zinc-500">
          Manual lumpsums (one-off cash events)
        </div>
        <button
          onClick={addEvent}
          className="flex items-center gap-1 text-[11px] text-[color:var(--color-accent,#5f7d56)] hover:underline"
        >
          <Plus size={12} /> Add event
        </button>
      </div>

      {events.length === 0 ? (
        <p className="text-[11px] text-zinc-400 italic">
          No manual events. Add a bonus, reverse mortgage, asset sale, or one-off expense.
        </p>
      ) : (
        <table className="w-full text-xs mb-3">
          <thead>
            <tr className="text-left text-zinc-500 border-b border-zinc-100">
              <th className="py-1 font-medium w-20">Year</th>
              <th className="py-1 font-medium w-32">Amount (₹)</th>
              <th className="py-1 font-medium">Label</th>
              <th className="py-1 w-6" />
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => (
              <tr key={e.id} className="border-b border-zinc-100 last:border-0">
                <td className="py-1 pr-2">
                  <input
                    className="w-16 border border-zinc-200 rounded px-1.5 py-0.5 text-xs tabular-nums"
                    inputMode="numeric"
                    value={e.year ?? ''}
                    onChange={(ev) => updateEvent(i, { year: Number(ev.target.value) })}
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    className="w-28 border border-zinc-200 rounded px-1.5 py-0.5 text-xs tabular-nums"
                    inputMode="numeric"
                    placeholder="+ deposit / − expense"
                    value={e.amount ?? ''}
                    onChange={(ev) => updateEvent(i, { amount: Number(ev.target.value) })}
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    className="w-full border border-zinc-200 rounded px-1.5 py-0.5 text-xs"
                    placeholder="e.g. Reverse mortgage"
                    value={e.label ?? ''}
                    onChange={(ev) => updateEvent(i, { label: ev.target.value })}
                  />
                </td>
                <td className="py-1">
                  <button onClick={() => removeEvent(i)} className="text-zinc-400 hover:text-rose-600" title="Remove">
                    <X size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="flex items-center gap-3 mt-1">
        <button
          onClick={saveEvents}
          className="text-xs font-medium bg-[color:var(--color-accent,#5f7d56)] text-white rounded-md px-3.5 py-1.5"
        >
          Save events
        </button>
        <span className="text-[10px] text-zinc-400">
          Positive = cash inflow (deposit), negative = one-off expense.
        </span>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  value,
  onChange,
  onCommit,
  placeholder,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  onCommit: () => void;
  placeholder: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <input
        className="border border-zinc-200 rounded-md px-2.5 py-1.5 text-sm tabular-nums"
        inputMode="numeric"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onCommit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        }}
      />
      <span className="text-[10px] text-zinc-400">{hint}</span>
    </label>
  );
}
