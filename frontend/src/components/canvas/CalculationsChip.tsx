'use client';

import { useCallback, useEffect, useState } from 'react';
import { Calculator, X, ChevronDown, ChevronRight } from 'lucide-react';
import { formatINR } from '@/lib/utils';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

/**
 * "Calculations" chip — always present in the canvas. Click it and a side
 * panel slides in showing the Excel-faithful CFP computation trace: every
 * step with its formula, inputs, and value. The user gets the math without
 * having to ask the agent for it. Refetches whenever the plan changes
 * (listens for `sw:plan-changed` like the canvas does).
 */
export function CalculationsChip({ householdId }: { householdId: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<CFPResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`${BACKEND}/api/skill/cfp/${householdId}`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as CFPResponse;
      setData(j);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [householdId]);

  // Refresh when the plan changes (in case a chat turn added a goal etc.).
  useEffect(() => {
    if (!open) return;
    load();
    const handler = () => load();
    window.addEventListener('sw:plan-changed', handler);
    return () => window.removeEventListener('sw:plan-changed', handler);
  }, [open, load]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 text-xs px-3 h-8 rounded-md border border-zinc-200 bg-white text-zinc-700 hover:text-zinc-900 hover:border-zinc-300"
        title="See the math behind every number"
      >
        <Calculator size={13} />
        Calculations
      </button>

      {open && (
        <div className="fixed inset-0 z-40">
          {/* backdrop */}
          <div
            className="absolute inset-0 bg-zinc-900/30"
            onClick={() => setOpen(false)}
          />
          {/* panel */}
          <aside className="absolute right-0 top-0 bottom-0 w-full max-w-[640px] bg-white shadow-2xl overflow-y-auto border-l border-zinc-200">
            <header className="sticky top-0 bg-white border-b border-zinc-200 px-5 py-3 flex items-center justify-between z-10">
              <div>
                <h2 className="text-sm font-medium text-zinc-900">Calculations</h2>
                <p className="text-[11px] text-zinc-500">
                  Every number on this plan, with the formula behind it. Mirrors the firm's CFP Excel.
                </p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="w-7 h-7 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
              >
                <X size={15} />
              </button>
            </header>

            <div className="px-5 py-4">
              {busy && !data && <p className="text-sm text-zinc-500">Computing…</p>}
              {err && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                  Couldn't load: {err}
                </div>
              )}
              {data && <CFPRender data={data} />}
            </div>
          </aside>
        </div>
      )}
    </>
  );
}

// ── data shape ────────────────────────────────────────────────────────────

type TraceStep = {
  label: string;
  formula: string;
  inputs: Record<string, unknown>;
  value: number | string;
  unit: string;
};

type GoalBlock = {
  goal_name: string;
  target_year: number;
  years_to_go: number;
  today_cost: number;
  inflation_used: number;
  future_value_needed: number;
  fv_gap: number;
  effective_return: number;
  required_sip_monthly: number;
  computation_trace: TraceStep[];
};

type CFPResponse = {
  summary: Record<string, number | string | boolean>;
  goal_blocks: GoalBlock[];
  retirement: { corpus_required: number; annual_expenses_at_retirement: number; real_return_used: number; computation_trace: TraceStep[] };
  insurance: { human_life_value: number; needs_based_corpus: number; average: number; additional_cover_required: number; computation_trace: TraceStep[] };
  yoy_cashflow: Array<Record<string, number>>;
  computation_trace: TraceStep[];
};

// ── rendering ─────────────────────────────────────────────────────────────

function CFPRender({ data }: { data: CFPResponse }) {
  return (
    <div className="flex flex-col gap-5">
      <Section title="Summary" defaultOpen>
        <table className="w-full text-sm">
          <tbody>
            {Object.entries(data.summary).map(([k, v]) => (
              <tr key={k} className="border-b border-zinc-100 last:border-0">
                <td className="py-1.5 text-zinc-500">{humanizeKey(k)}</td>
                <td className="py-1.5 text-right tabular-nums text-zinc-900">{fmt(v, k)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title={`Top-level trace (${data.computation_trace.length} steps)`}>
        <TraceList steps={data.computation_trace} />
      </Section>

      {data.goal_blocks.map((g) => (
        <Section
          key={g.goal_name}
          title={`Goal — ${g.goal_name}`}
          subtitle={`target ${g.target_year} · ${g.years_to_go}y out · SIP ₹${g.required_sip_monthly.toLocaleString('en-IN')}/mo`}
        >
          <GoalSummary g={g} />
          <div className="mt-3">
            <p className="text-xs text-zinc-500 mb-2">Computation steps</p>
            <TraceList steps={g.computation_trace} />
          </div>
        </Section>
      ))}

      <Section
        title="Retirement"
        subtitle={`corpus required ${formatINR(data.retirement.corpus_required, { compact: true })}`}
      >
        <TraceList steps={data.retirement.computation_trace} />
      </Section>

      <Section
        title="Insurance need"
        subtitle={`additional cover ${formatINR(data.insurance.additional_cover_required, { compact: true })}`}
      >
        <TraceList steps={data.insurance.computation_trace} />
      </Section>

      <Section title={`Year-by-year cashflow (${data.yoy_cashflow.length} rows)`}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-zinc-500">
              <tr>
                <th className="text-left py-1.5 pr-3">Year</th>
                <th className="text-left py-1.5 pr-3">Age</th>
                <th className="text-right py-1.5 pr-3">Income</th>
                <th className="text-right py-1.5 pr-3">Expenses</th>
                <th className="text-right py-1.5 pr-3">Surplus</th>
                <th className="text-right py-1.5">Net worth</th>
              </tr>
            </thead>
            <tbody>
              {data.yoy_cashflow.slice(0, 20).map((row) => (
                <tr key={row.year} className="border-t border-zinc-100">
                  <td className="py-1.5 pr-3 tabular-nums">{row.year}</td>
                  <td className="py-1.5 pr-3 tabular-nums">{row.age}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{formatINR(row.total_income, { compact: true })}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{formatINR(row.expenses, { compact: true })}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{formatINR(row.surplus, { compact: true })}</td>
                  <td className="py-1.5 text-right tabular-nums font-medium">{formatINR(row.net_worth, { compact: true })}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.yoy_cashflow.length > 20 && (
            <p className="text-[11px] text-zinc-400 mt-2">+{data.yoy_cashflow.length - 20} more years…</p>
          )}
        </div>
      </Section>
    </div>
  );
}

function Section({
  title,
  subtitle,
  defaultOpen,
  children,
}: {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <section className="rounded-xl border border-zinc-200 bg-white">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-zinc-50"
      >
        <div>
          <h3 className="text-sm font-medium text-zinc-900">{title}</h3>
          {subtitle && <p className="text-[11px] text-zinc-500 mt-0.5">{subtitle}</p>}
        </div>
        {open ? <ChevronDown size={15} className="text-zinc-400" /> : <ChevronRight size={15} className="text-zinc-400" />}
      </button>
      {open && <div className="px-4 pb-4 border-t border-zinc-100">{children}</div>}
    </section>
  );
}

function GoalSummary({ g }: { g: GoalBlock }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs mt-1">
      <KV label="Today's cost" value={formatINR(g.today_cost, { compact: true })} />
      <KV label="Inflation used" value={`${(g.inflation_used * 100).toFixed(1)}%`} />
      <KV label="Future value needed" value={formatINR(g.future_value_needed, { compact: true })} />
      <KV label="FV gap" value={formatINR(g.fv_gap, { compact: true })} />
      <KV label="Effective return (glide-path)" value={`${(g.effective_return * 100).toFixed(1)}%`} />
      <KV label="Required SIP / month" value={formatINR(g.required_sip_monthly, { compact: true })} bold />
    </div>
  );
}

function KV({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-zinc-500">{label}</span>
      <span className={`tabular-nums ${bold ? 'text-zinc-900 font-medium' : 'text-zinc-700'}`}>{value}</span>
    </div>
  );
}

function TraceList({ steps }: { steps: TraceStep[] }) {
  return (
    <ol className="flex flex-col gap-2">
      {steps.map((s, i) => (
        <li key={i} className="rounded-lg border border-zinc-100 bg-zinc-50/50 px-3 py-2">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm text-zinc-900">{s.label}</span>
            <span className="tabular-nums text-sm font-medium text-zinc-900">
              {formatValue(s.value, s.unit)}
            </span>
          </div>
          <p className="text-[11px] text-zinc-500 font-mono mt-1">{s.formula}</p>
          {Object.keys(s.inputs).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {Object.entries(s.inputs).map(([k, v]) => (
                <span
                  key={k}
                  className="text-[10px] tabular-nums px-1.5 py-0.5 rounded bg-white border border-zinc-200 text-zinc-600"
                >
                  {k} = {formatInput(v)}
                </span>
              ))}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

// ── formatters ───────────────────────────────────────────────────────────

function fmt(v: unknown, key: string): string {
  if (v == null) return '—';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'string') return v;
  if (typeof v === 'number') {
    if (key.endsWith('_rate')) return `${(v * 100).toFixed(2)}%`;
    if (key.includes('age') || key.includes('years')) return String(Math.round(v));
    return formatINR(v, { compact: Math.abs(v) >= 1_00_000 });
  }
  return JSON.stringify(v);
}

function formatValue(v: number | string, unit: string): string {
  if (typeof v === 'string') return v;
  if (unit === '%') return `${(v * 100).toFixed(2)}%`;
  if (unit === 'bool') return String(v);
  if (Math.abs(v) >= 1_00_000) return formatINR(v, { compact: true });
  return v.toLocaleString('en-IN');
}

function formatInput(v: unknown): string {
  if (Array.isArray(v)) return `[${v.length}]`;
  if (typeof v === 'number') {
    if (v > 0 && v < 1) return v.toString();
    if (Math.abs(v) >= 1_00_000) return formatINR(v, { compact: true }).replace('₹', '');
    return v.toLocaleString('en-IN');
  }
  return String(v);
}

function humanizeKey(k: string): string {
  return k.replace(/_/g, ' ').replace(/\bi\b/, '').trim();
}
