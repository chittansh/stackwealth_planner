'use client';

import { useState, useMemo } from 'react';
import { ChevronRight, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { ToolCallCard, type ToolState } from './ToolCallCard';

export type GroupedTool = {
  id: string;
  name: string;
  args: unknown;
  result?: unknown;
  state: ToolState;
};

/**
 * Collapses a run of consecutive tool calls into a single "tool calls" row.
 * Header reflects aggregate state (running while any are pending, error if
 * any failed, otherwise done). Click to reveal the individual tool cards.
 *
 * Auto-expands while at least one tool is still running so the user sees
 * progress live; collapses again on done so the chat stays calm.
 */
export function ToolGroup({ tools }: { tools: GroupedTool[] }) {
  const aggregate = useMemo<ToolState>(() => {
    if (tools.some((t) => t.state === 'running')) return 'running';
    if (tools.some((t) => t.state === 'error')) return 'error';
    return 'done';
  }, [tools]);

  // Default open while running; collapsed once everything is done.
  const [userToggled, setUserToggled] = useState(false);
  const [open, setOpen] = useState(true);

  // While running, force-open. Once done, respect user's last toggle but
  // default-collapse the first time we hit done.
  const effectivelyOpen = aggregate === 'running' ? true : userToggled ? open : false;

  const running = aggregate === 'running';
  return (
    <div className="self-start max-w-[280px] w-full">
      <button
        type="button"
        onClick={() => {
          setUserToggled(true);
          setOpen((v) => !v);
        }}
        disabled={running}
        className={`w-full flex items-center gap-1.5 px-2 py-1.5 rounded-md transition disabled:opacity-100 ${
          running
            ? 'bg-[var(--color-accent-soft)] border border-[var(--color-accent-2)]/40'
            : 'text-zinc-500 hover:bg-zinc-50 border border-transparent'
        }`}
      >
        <ChevronRight
          size={10}
          className={`shrink-0 transition-transform ${running ? 'text-[color:var(--color-accent)]/60' : 'text-zinc-300'} ${effectivelyOpen ? 'rotate-90' : ''}`}
        />
        <Aggregate state={aggregate} />
        <span
          className={`text-[11px] flex-1 text-left ${
            running ? 'text-[color:var(--color-accent)] font-medium' : 'text-zinc-500'
          }`}
        >
          {running ? (
            <>
              <span className="sw-running-dots">Running</span> {tools.length} tool
              {tools.length === 1 ? '' : 's'}
            </>
          ) : (
            <>
              {tools.length} tool {tools.length === 1 ? 'call' : 'calls'}
            </>
          )}
        </span>
        <span
          className={`text-[10px] font-mono truncate max-w-[120px] ${
            running ? 'text-[color:var(--color-accent)]/70' : 'text-zinc-300'
          }`}
        >
          {summarize(tools)}
        </span>
      </button>
      {/* tiny CSS for the typewriter dots */}
      <style>{`
        .sw-running-dots::after {
          content: '';
          display: inline-block;
          width: 1.2em;
          text-align: left;
          animation: sw-dots 1.2s steps(4, end) infinite;
        }
        @keyframes sw-dots {
          0%   { content: ''; }
          25%  { content: '.'; }
          50%  { content: '..'; }
          75%  { content: '...'; }
          100% { content: ''; }
        }
      `}</style>

      {effectivelyOpen && (
        <div className="ml-3 mt-0.5 mb-1 pl-2 border-l border-zinc-100 flex flex-col gap-0.5">
          {tools.map((t) => (
            <ToolCallCard
              key={t.id}
              name={t.name}
              args={t.args}
              result={t.result}
              state={t.state}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Aggregate({ state }: { state: ToolState }) {
  if (state === 'running') {
    return <Loader2 size={12} className="animate-spin shrink-0" style={{ color: 'var(--color-accent)' }} />;
  }
  if (state === 'error') return <AlertCircle size={11} className="shrink-0 text-zinc-500" />;
  return <CheckCircle2 size={11} className="shrink-0" style={{ color: 'var(--color-accent)' }} />;
}

function summarize(tools: GroupedTool[]): string {
  // Show up to three unique tool names, comma-separated.
  const names: string[] = [];
  for (const t of tools) {
    if (!names.includes(t.name)) names.push(t.name);
    if (names.length === 3) break;
  }
  const more = new Set(tools.map((t) => t.name)).size - names.length;
  return more > 0 ? `${names.join(', ')} +${more}` : names.join(', ');
}
