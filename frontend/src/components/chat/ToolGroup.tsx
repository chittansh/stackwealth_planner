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

  return (
    <div className="self-start max-w-[280px] w-full">
      <button
        type="button"
        onClick={() => {
          setUserToggled(true);
          setOpen((v) => !v);
        }}
        disabled={aggregate === 'running'}
        className="w-full flex items-center gap-1.5 px-1.5 py-1 rounded-md text-zinc-500 hover:bg-zinc-50 disabled:opacity-100"
      >
        <ChevronRight
          size={9}
          className={`shrink-0 transition-transform text-zinc-300 ${effectivelyOpen ? 'rotate-90' : ''}`}
        />
        <Aggregate state={aggregate} />
        <span className="text-[10.5px] flex-1 text-left">
          {tools.length} tool {tools.length === 1 ? 'call' : 'calls'}
        </span>
        <span className="text-[9.5px] text-zinc-300 font-mono truncate max-w-[120px]">
          {summarize(tools)}
        </span>
      </button>

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
    return <Loader2 size={9} className="animate-spin shrink-0" style={{ color: 'var(--color-accent)' }} />;
  }
  if (state === 'error') return <AlertCircle size={9} className="shrink-0 text-zinc-500" />;
  return <CheckCircle2 size={9} className="shrink-0" style={{ color: 'var(--color-accent)' }} />;
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
