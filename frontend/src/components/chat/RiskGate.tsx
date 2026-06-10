'use client';

import { useState } from 'react';
import { ChevronLeft, ChevronRight, TrendingDown, Scale, AlertTriangle, Check } from 'lucide-react';
import { firePlanChanged } from '@/lib/prompt';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type Option = { id: string; label: string; sub?: string };

type Question = {
  key: 'volatility_reaction' | 'risk_return_tradeoff' | 'max_tolerable_loss';
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  prompt: string;
  options: readonly Option[];
};

const QUESTIONS: Question[] = [
  {
    key: 'volatility_reaction',
    Icon: TrendingDown,
    title: 'Market shock reaction',
    prompt: 'If your portfolio dropped 20% in a single month, you would…',
    options: [
      { id: 'sell_everything', label: 'Sell everything',  sub: "I can't watch it bleed" },
      { id: 'sell_some',       label: 'Sell some',        sub: 'Trim risk and reassess' },
      { id: 'hold_steady',     label: 'Hold steady',      sub: 'Stay invested through the cycle' },
      { id: 'buy_more',        label: 'Buy more',         sub: 'Dips are buying opportunities' },
    ],
  },
  {
    key: 'risk_return_tradeoff',
    Icon: Scale,
    title: 'Risk / return tradeoff',
    prompt: 'Which growth profile best describes you?',
    options: [
      { id: 'A', label: 'Preserve capital', sub: 'Low return, very low risk' },
      { id: 'B', label: 'Modest growth',    sub: 'Small risk for above-FD returns' },
      { id: 'C', label: 'Balanced growth',  sub: 'Equal weight on risk + return' },
      { id: 'D', label: 'Maximum growth',   sub: 'Higher risk accepted for higher returns' },
    ],
  },
  {
    key: 'max_tolerable_loss',
    Icon: AlertTriangle,
    title: 'Loss tolerance',
    prompt: "What's the most you could lose in a single year without losing sleep?",
    options: [
      { id: '0',   label: '0%',           sub: 'Capital is sacred' },
      { id: '10',  label: 'Up to 10%',    sub: 'Mild dips OK' },
      { id: '20',  label: 'Up to 20%',    sub: 'Normal market volatility' },
      { id: '30',  label: 'Up to 30%',    sub: 'Real drawdowns survivable' },
      { id: '>30', label: 'More than 30%', sub: 'Bear markets are part of the game' },
    ],
  },
];

export function RiskGate({
  householdId,
  onComplete,
}: {
  householdId: string;
  onComplete: () => void;
}) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const total = QUESTIONS.length;
  const done = Object.keys(answers).length === total;
  const q = QUESTIONS[Math.min(step, total - 1)];

  const pick = (id: string) => {
    const next = { ...answers, [q.key]: id };
    setAnswers(next);
    // Auto-advance with a tiny pause so the selection feedback is visible.
    setTimeout(() => setStep((s) => Math.min(s + 1, total)), 180);
  };

  const submit = async () => {
    setBusy(true);
    try {
      await fetch(`${BACKEND}/api/skill/risk/${householdId}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ willingness: answers }),
      });
      firePlanChanged();
      onComplete();
    } finally {
      setBusy(false);
    }
  };

  // Final screen — show all three answers + Compute CTA.
  if (step >= total) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-1.5 mb-3">
          {QUESTIONS.map((_, i) => (
            <span key={i} className="w-6 h-1 rounded-full bg-emerald-500" />
          ))}
          <span className="ml-2 text-[10px] text-zinc-400 uppercase tracking-wide">All three answered</span>
        </div>
        <h4 className="text-sm font-medium text-zinc-900 mb-3">Review &amp; lock in</h4>
        <div className="flex flex-col gap-2 mb-4">
          {QUESTIONS.map((qq, i) => {
            const a = qq.options.find((o) => o.id === answers[qq.key]);
            return (
              <button
                key={qq.key}
                onClick={() => setStep(i)}
                className="text-left flex items-center justify-between px-3 py-2 rounded-lg border border-zinc-100 bg-zinc-50/60 hover:bg-zinc-50"
              >
                <span className="flex items-center gap-2 text-xs">
                  <qq.Icon size={13} className="text-zinc-400" />
                  <span className="text-zinc-500">{qq.title}</span>
                </span>
                <span className="text-xs font-medium text-zinc-800">{a?.label ?? '—'}</span>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setStep(total - 1)}
            disabled={busy}
            className="text-xs px-3 h-8 rounded-md border border-zinc-200 hover:bg-zinc-50 text-zinc-700"
          >
            <ChevronLeft size={13} className="inline" /> Back
          </button>
          <button
            onClick={submit}
            disabled={busy || !done}
            className="text-xs px-3 h-8 rounded-md text-white inline-flex items-center gap-1 disabled:opacity-50"
            style={{ background: 'var(--color-accent)' }}
          >
            {busy ? 'Computing…' : (<>Compute risk profile <Check size={13} /></>)}
          </button>
        </div>
      </div>
    );
  }

  // Active question card.
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm">
      {/* Stepper */}
      <div className="flex items-center gap-1.5 mb-3">
        {QUESTIONS.map((_, i) => (
          <span
            key={i}
            className={`w-6 h-1 rounded-full transition-colors ${
              i < step ? 'bg-emerald-500' : i === step ? 'bg-zinc-900' : 'bg-zinc-200'
            }`}
          />
        ))}
        <span className="ml-2 text-[10px] text-zinc-400 uppercase tracking-wide">
          {step + 1} of {total} · {q.title}
        </span>
      </div>

      {/* Prompt */}
      <p className="text-sm text-zinc-900 mb-3 leading-snug">{q.prompt}</p>

      {/* Option cards */}
      <div className="grid grid-cols-2 gap-2">
        {q.options.map((o) => {
          const selected = answers[q.key] === o.id;
          return (
            <button
              key={o.id}
              onClick={() => pick(o.id)}
              className={`text-left rounded-lg border px-3 py-2.5 transition ${
                selected
                  ? 'border-emerald-500 bg-emerald-50/40 ring-1 ring-emerald-500/30'
                  : 'border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50'
              }`}
            >
              <div className="text-xs font-medium text-zinc-900">{o.label}</div>
              {o.sub && <div className="text-[11px] text-zinc-500 mt-0.5 leading-snug">{o.sub}</div>}
            </button>
          );
        })}
      </div>

      {/* Footer nav */}
      <div className="flex items-center justify-between mt-3 pt-3 border-t border-zinc-100">
        <button
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
          className="text-xs text-zinc-500 hover:text-zinc-900 inline-flex items-center gap-1 disabled:opacity-30"
        >
          <ChevronLeft size={13} /> Back
        </button>
        <button
          onClick={() => setStep((s) => Math.min(total, s + 1))}
          disabled={!answers[q.key]}
          className="text-xs text-zinc-700 hover:text-zinc-900 inline-flex items-center gap-1 disabled:opacity-30"
        >
          Next <ChevronRight size={13} />
        </button>
      </div>
    </div>
  );
}
