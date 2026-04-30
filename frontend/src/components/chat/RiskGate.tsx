'use client';

import { useState } from 'react';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

const Q1 = [
  { id: 'sell_everything', label: 'Sell everything' },
  { id: 'sell_some', label: 'Sell some' },
  { id: 'hold_steady', label: 'Hold steady' },
  { id: 'buy_more', label: 'Buy more' },
] as const;
const Q2 = [
  { id: 'A', label: 'A — capital safety; low return' },
  { id: 'B', label: 'B — small risk; modest return' },
  { id: 'C', label: 'C — balanced risk and return' },
  { id: 'D', label: 'D — high risk for high return' },
] as const;
const Q3 = [
  { id: '0', label: '0%' },
  { id: '10', label: '10%' },
  { id: '20', label: '20%' },
  { id: '30', label: '30%' },
  { id: '>30', label: 'more than 30%' },
] as const;

export function RiskGate({
  householdId,
  onComplete,
}: {
  householdId: string;
  onComplete: () => void;
}) {
  const [step, setStep] = useState<0 | 1 | 2 | 3>(0);
  const [a1, setA1] = useState<typeof Q1[number]['id'] | ''>('');
  const [a2, setA2] = useState<typeof Q2[number]['id'] | ''>('');
  const [a3, setA3] = useState<typeof Q3[number]['id'] | ''>('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!a1 || !a2 || !a3) return;
    setBusy(true);
    try {
      await fetch(`${BACKEND}/api/skill/risk/${householdId}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          willingness: { volatility_reaction: a1, risk_return_tradeoff: a2, max_tolerable_loss: a3 },
        }),
      });
      onComplete();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-3 text-sm flex flex-col gap-3">
      <div className="text-xs text-zinc-500">Quick risk check — 3 questions.</div>

      {step === 0 && (
        <Step
          q="If your portfolio dropped 30% in a month, you would…"
          options={Q1}
          value={a1}
          onPick={(v) => {
            setA1(v as typeof a1);
            setStep(1);
          }}
        />
      )}
      {step === 1 && (
        <Step
          q="Which return / risk tradeoff fits you best?"
          options={Q2}
          value={a2}
          onPick={(v) => {
            setA2(v as typeof a2);
            setStep(2);
          }}
        />
      )}
      {step === 2 && (
        <Step
          q="What's the most you could tolerate losing in a year?"
          options={Q3}
          value={a3}
          onPick={(v) => {
            setA3(v as typeof a3);
            setStep(3);
          }}
        />
      )}
      {step === 3 && (
        <button
          onClick={submit}
          disabled={busy || !a1 || !a2 || !a3}
          className="self-start text-xs px-3 py-1.5 rounded-md bg-zinc-900 text-white disabled:opacity-50"
        >
          {busy ? 'Computing…' : 'Compute risk profile'}
        </button>
      )}
    </div>
  );
}

function Step({
  q,
  options,
  value,
  onPick,
}: {
  q: string;
  options: readonly { id: string; label: string }[];
  value: string;
  onPick: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-zinc-700">{q}</p>
      <div className="flex flex-col gap-1">
        {options.map((o) => (
          <button
            key={o.id}
            onClick={() => onPick(o.id)}
            className={`text-left text-xs px-2 py-1.5 rounded-md border ${
              value === o.id ? 'border-zinc-900 bg-zinc-50 text-zinc-900' : 'border-zinc-200 hover:bg-zinc-50 text-zinc-700'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
