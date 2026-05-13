'use client';

import { useState } from 'react';
import { ChevronRight, CheckCircle2, AlertCircle, Loader2, Wrench } from 'lucide-react';

export type ToolState = 'running' | 'done' | 'error';

const FRIENDLY: Record<string, string> = {
  intake_ingest: 'reading file',
  intake_confirm: 'confirming',
  plan_set: 'updating plan',
  plan_add: 'adding row',
  plan_remove: 'removing row',
  plan_assumption: 'updating assumption',
  risk_assess: 'risk profile',
  allocate_recommend: 'allocation',
  freedom_score: 'freedom score',
  tax_harvest: 'tax view',
  cashflow_project: 'cashflow',
  scenario_pin: 'pinning scenario',
  scenario_diff: 'comparing',
  montecarlo_run: 'monte carlo',
  debt_paydown: 'debt paydown',
  knowledge_retrieve: 'knowledge base',
  news_relevance: 'news',
};

/**
 * Compact, collapsed-by-default tool log row. One thin line per call —
 * tap to expand and see the args / result JSON.
 */
export function ToolCallCard({
  name,
  args,
  result,
  state,
}: {
  name: string;
  args: unknown;
  result: unknown;
  state: ToolState;
}) {
  const [open, setOpen] = useState(false);
  const friendly = FRIENDLY[name] ?? name;
  const errored =
    state === 'error' ||
    (result &&
      typeof result === 'object' &&
      'error' in (result as Record<string, unknown>) &&
      typeof (result as { error: unknown }).error === 'string');

  const running = state === 'running';
  return (
    <div className="self-start max-w-[280px] w-full">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center gap-1.5 px-1.5 py-1 rounded-md transition ${
          running
            ? 'bg-[var(--color-accent-soft)] text-[color:var(--color-accent)]'
            : 'text-zinc-500 hover:bg-zinc-50'
        }`}
      >
        <ChevronRight
          size={9}
          className={`shrink-0 transition-transform ${running ? 'text-[color:var(--color-accent)]/60' : 'text-zinc-300'} ${open ? 'rotate-90' : ''}`}
        />
        <StateIcon state={state} errored={errored} />
        <span className={`text-[10.5px] truncate flex-1 text-left ${running ? 'font-medium' : ''}`}>
          {friendly}
        </span>
        <code className={`text-[9.5px] font-mono ${running ? 'text-[color:var(--color-accent)]/70' : 'text-zinc-300'}`}>
          {name}
        </code>
      </button>

      {open && (
        <div className="ml-4 mt-1 mb-1 rounded-md border border-zinc-100 bg-zinc-50/60 px-2 py-1.5 space-y-1.5">
          <Section label="args">
            <Json value={args} />
          </Section>
          <Section label="result">
            {result === undefined ? (
              <div className="text-[10px] italic text-zinc-400">running…</div>
            ) : (
              <Json value={result} />
            )}
          </Section>
        </div>
      )}
    </div>
  );
}

function StateIcon({ state, errored }: { state: ToolState; errored: boolean | unknown }) {
  if (state === 'running') {
    return <Loader2 size={11} className="animate-spin shrink-0" style={{ color: 'var(--color-accent)' }} />;
  }
  if (errored) return <AlertCircle size={10} className="shrink-0 text-zinc-500" />;
  if (state === 'done') return <CheckCircle2 size={10} className="shrink-0" style={{ color: 'var(--color-accent)' }} />;
  return <Wrench size={10} className="shrink-0 text-zinc-300" />;
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[8.5px] uppercase tracking-wider text-zinc-400 mb-0.5">{label}</div>
      {children}
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  let formatted: string;
  try {
    formatted = JSON.stringify(value, null, 2);
  } catch {
    formatted = String(value);
  }
  const MAX = 1500;
  const truncated = formatted.length > MAX;
  const shown = truncated ? formatted.slice(0, MAX) + '\n…' : formatted;
  return (
    <pre className="scrollbar-hidden text-[9.5px] font-mono leading-snug text-zinc-700 whitespace-pre-wrap break-words bg-white rounded p-1.5 max-h-[140px] overflow-auto">
      {shown}
      {truncated && <span className="text-zinc-400"> ({formatted.length - MAX} more chars)</span>}
    </pre>
  );
}
