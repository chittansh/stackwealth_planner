'use client';

import { useState } from 'react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';

type Mode = 'excel' | 'assets' | 'cashflow';

/**
 * Year-by-year projection table. Three switchable views:
 *
 *  • Excel — full Excel-faithful YoY Cash Flow tab. Mirrors the firm's
 *    workbook column-for-column (Summary of Income & Expenditure +
 *    Computing Financial Assets + Computing Non-Financial Assets +
 *    Total Net Worth). Reads from `plan.computed.cfp.yoy_cashflow`.
 *
 *  • Assets — end-of-year breakdown by asset class with a composition
 *    bar per row. Reads from `plan.computed.cash_flow_table` (legacy
 *    cashflow engine output).
 *
 *  • Cashflow — inflows / outflows / net surplus per year.
 *
 * The Excel view is the default since the firm's RM workflow is built
 * around the workbook layout — it's the most direct mapping for an
 * advisor doing year-by-year analysis.
 */
export function CashFlowTable({ plan }: { plan: PlanState | null }) {
  const [mode, setMode] = useState<Mode>('excel');
  const legacyRows = plan?.computed.cash_flow_table ?? [];
  const yoyRows =
    ((plan?.computed.cfp as { yoy_cashflow?: YoyRow[] } | undefined)?.yoy_cashflow as YoyRow[] | undefined) ?? [];

  const hasYoy = yoyRows.length > 0;
  const effectiveMode = mode === 'excel' && !hasYoy ? 'assets' : mode;

  if (!legacyRows.length && !hasYoy) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        Cash flow appears once income and expenses are set. Drop a statement or paste your numbers.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-zinc-200 overflow-hidden bg-white">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
        <div>
          <h3 className="text-sm font-medium text-zinc-800">Year-by-year projection</h3>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            {effectiveMode === 'excel'
              ? 'Mirrors the firm YoY Cash Flow workbook tab column-for-column.'
              : effectiveMode === 'assets'
              ? 'End-of-year breakdown by asset class.'
              : 'Inflows and outflows per year.'}
          </p>
        </div>
        <div className="inline-flex items-center rounded-lg border border-zinc-200 p-0.5 text-[11px]">
          {hasYoy && (
            <ModeButton active={effectiveMode === 'excel'} onClick={() => setMode('excel')}>
              Excel
            </ModeButton>
          )}
          <ModeButton active={effectiveMode === 'assets'} onClick={() => setMode('assets')}>
            Assets
          </ModeButton>
          <ModeButton active={effectiveMode === 'cashflow'} onClick={() => setMode('cashflow')}>
            Cashflow
          </ModeButton>
        </div>
      </div>

      <div className="max-h-[560px] overflow-auto">
        {effectiveMode === 'excel' ? (
          <ExcelTable rows={yoyRows} />
        ) : effectiveMode === 'assets' ? (
          <AssetsTable rows={legacyRows} />
        ) : (
          <CashflowTableInner rows={legacyRows} />
        )}
      </div>
    </div>
  );
}

/* ── Excel-faithful view ───────────────────────────────────────────── */

type YoyRow = {
  year: number;
  age: number;
  income_employment: number;
  income_business: number;
  income_rental: number;
  income_other: number;
  total_income: number;
  expenses: number;
  loan_repayment: number;
  total_outflow: number;
  surplus: number;
  fa_opening?: number;
  net_annual_cash_savings?: number;
  major_withdrawals?: number;
  investment_returns?: number;
  lumpsum_deposit_withdrawal?: number;
  remarks?: string;
  goal_remarks?: string;
  financial_assets_closing: number;
  nfa_opening?: number;
  nfa_addition?: number;
  nfa_appreciation?: number;
  non_financial_assets_closing: number;
  net_worth: number;
  net_worth_crore: number;
  goal_withdrawal?: number;
};

function ExcelTable({ rows }: { rows: YoyRow[] }) {
  return (
    <table className="min-w-full text-[11px] tabular-nums">
      {/* Two-row header with section labels above the column groups */}
      <thead className="sticky top-0 bg-zinc-50 text-zinc-500 z-10">
        <tr className="text-[10px] uppercase tracking-wide text-zinc-400 bg-zinc-100/50">
          <th colSpan={3} className="px-2 py-1.5 text-left border-b border-zinc-200 font-medium">
            Income & expenditure
          </th>
          <th colSpan={5} className="px-2 py-1.5 text-right border-b border-zinc-200 border-l border-zinc-200 font-medium">
            Income
          </th>
          <th colSpan={4} className="px-2 py-1.5 text-right border-b border-zinc-200 border-l border-zinc-200 font-medium">
            Outflow
          </th>
          <th colSpan={7} className="px-2 py-1.5 text-right border-b border-zinc-200 border-l border-zinc-200 font-medium">
            Financial assets
          </th>
          <th colSpan={3} className="px-2 py-1.5 text-right border-b border-zinc-200 border-l border-zinc-200 font-medium">
            Non-financial assets
          </th>
          <th colSpan={2} className="px-2 py-1.5 text-right border-b border-zinc-200 border-l border-zinc-200 font-medium">
            Net worth
          </th>
        </tr>
        <tr className="text-[10px] uppercase tracking-wide">
          <Th>Year</Th>
          <Th right>Yr</Th>
          <Th right>Age</Th>
          <Th right>Salary</Th>
          <Th right>Business</Th>
          <Th right>Rental</Th>
          <Th right>Other</Th>
          <Th right strong>Total in</Th>
          <Th right>Expenses</Th>
          <Th right>EMI</Th>
          <Th right strong>Total out</Th>
          <Th right strong>Surplus</Th>
          <Th right>Open FA</Th>
          <Th right>Withdraw</Th>
          <Th>Purpose</Th>
          <Th right>Returns</Th>
          <Th right>Lumpsum</Th>
          <Th>Remarks</Th>
          <Th right strong>Close FA</Th>
          <Th right>Open NFA</Th>
          <Th right>Apprn</Th>
          <Th right strong>Close NFA</Th>
          <Th right strong>Total NW</Th>
          <Th right>Cr</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const yr = `Y${i}`;
          const withdraw = r.major_withdrawals ?? -(r.goal_withdrawal ?? 0);
          const lumpsum = r.lumpsum_deposit_withdrawal ?? 0;
          const remarks = r.remarks ?? '';
          const purpose = r.goal_remarks ?? '';
          return (
            <tr key={i} className="border-b border-zinc-100 hover:bg-zinc-50/60">
              <Td>{yr}</Td>
              <Td right>{r.year}</Td>
              <Td right>{Math.round(r.age)}</Td>
              <Td right>{r.income_employment > 0 ? fmt(r.income_employment) : '—'}</Td>
              <Td right>{r.income_business > 0 ? fmt(r.income_business) : '—'}</Td>
              <Td right>{r.income_rental > 0 ? fmt(r.income_rental) : '—'}</Td>
              <Td right>{r.income_other > 0 ? fmt(r.income_other) : '—'}</Td>
              <Td right strong tone={r.total_income > 0 ? 'good' : undefined}>
                {fmt(r.total_income)}
              </Td>
              <Td right>{fmt(r.expenses)}</Td>
              <Td right>{r.loan_repayment > 0 ? fmt(r.loan_repayment) : '—'}</Td>
              <Td right strong>{fmt(r.total_outflow)}</Td>
              <Td right strong tone={r.surplus >= 0 ? 'good' : 'bad'}>
                {r.surplus >= 0 ? fmt(r.surplus) : `−${fmt(-r.surplus)}`}
              </Td>
              <Td right>{fmt(r.fa_opening ?? 0)}</Td>
              <Td right tone={withdraw < 0 ? 'warn' : undefined}>
                {withdraw !== 0 ? fmt(withdraw) : '—'}
              </Td>
              <Td>{purpose ? <span className="text-zinc-600 italic whitespace-normal">{purpose}</span> : <span className="text-zinc-300">—</span>}</Td>
              <Td right>{fmt(r.investment_returns ?? 0)}</Td>
              <Td right tone={lumpsum !== 0 ? (lumpsum > 0 ? 'good' : 'warn') : undefined}>
                {lumpsum !== 0 ? fmt(lumpsum) : '—'}
              </Td>
              <Td>{remarks ? <span className="text-zinc-500 italic whitespace-normal">{remarks}</span> : <span className="text-zinc-300">—</span>}</Td>
              <Td right strong>{fmt(r.financial_assets_closing)}</Td>
              <Td right>{fmt(r.nfa_opening ?? 0)}</Td>
              <Td right>{fmt(r.nfa_appreciation ?? 0)}</Td>
              <Td right strong>{fmt(r.non_financial_assets_closing)}</Td>
              <Td right strong>{fmt(r.net_worth)}</Td>
              <Td right>{r.net_worth_crore.toFixed(2)}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ── Asset-class view (existing) ───────────────────────────────────── */

type Row = NonNullable<PlanState['computed']['cash_flow_table']>[number];

function AssetsTable({ rows }: { rows: Row[] }) {
  return (
    <table className="min-w-full text-xs tabular-nums">
      <thead className="sticky top-0 bg-zinc-50 text-zinc-500 z-10">
        <tr>
          <Th>Year</Th>
          <Th right>Age</Th>
          <Th right>Cash</Th>
          <Th right>Investments</Th>
          <Th right>Real estate</Th>
          <Th right>Gold</Th>
          <Th right>Goal spend</Th>
          <Th right>Net worth</Th>
          <Th>Composition</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const liquid = r.liquid ?? 0;
          const portfolio = r.portfolio ?? r.assets ?? 0;
          const realEstate = r.real_estate ?? 0;
          const gold = r.gold ?? 0;
          const goalOut = r.goal_outflow ?? 0;
          const total = r.total_net_worth || liquid + portfolio + realEstate + gold;
          return (
            <tr key={i} className="border-b border-zinc-100 hover:bg-zinc-50/60">
              <Td>{r.year}</Td>
              <Td right>{r.age}</Td>
              <Td right>{fmt(liquid)}</Td>
              <Td right>{fmt(portfolio)}</Td>
              <Td right>{fmt(realEstate)}</Td>
              <Td right>{fmt(gold)}</Td>
              <Td right tone={goalOut > 0 ? 'warn' : undefined}>
                {goalOut > 0 ? `−${fmt(goalOut)}` : '—'}
              </Td>
              <Td right strong>{fmt(total)}</Td>
              <td className="px-3 py-1.5 w-[140px]">
                <CompositionBar
                  liquid={liquid}
                  portfolio={portfolio}
                  realEstate={realEstate}
                  gold={gold}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ── Cashflow view (existing, condensed) ───────────────────────────── */

function CashflowTableInner({ rows }: { rows: Row[] }) {
  return (
    <table className="min-w-full text-xs tabular-nums">
      <thead className="sticky top-0 bg-zinc-50 text-zinc-500 z-10">
        <tr>
          <Th>Year</Th>
          <Th right>Age</Th>
          <Th right>Income</Th>
          <Th right>Expenses</Th>
          <Th right>Taxes</Th>
          <Th right>Goal spend</Th>
          <Th right>Net surplus</Th>
          <Th right>Net worth</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const surplus = r.income - r.expenses - r.taxes - (r.goal_outflow ?? 0);
          return (
            <tr key={i} className="border-b border-zinc-100 hover:bg-zinc-50/60">
              <Td>{r.year}</Td>
              <Td right>{r.age}</Td>
              <Td right tone={r.income > 0 ? 'good' : undefined}>{r.income > 0 ? fmt(r.income) : '—'}</Td>
              <Td right>{fmt(r.expenses)}</Td>
              <Td right>{r.taxes > 0 ? fmt(r.taxes) : '—'}</Td>
              <Td right tone={(r.goal_outflow ?? 0) > 0 ? 'warn' : undefined}>
                {(r.goal_outflow ?? 0) > 0 ? `−${fmt(r.goal_outflow ?? 0)}` : '—'}
              </Td>
              <Td right tone={surplus >= 0 ? 'good' : 'bad'}>
                {surplus >= 0 ? fmt(surplus) : `−${fmt(-surplus)}`}
              </Td>
              <Td right strong>{fmt(r.total_net_worth)}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────── */

function fmt(n: number): string {
  return formatINR(n, { compact: true });
}

function Th({
  children,
  right,
  strong,
}: {
  children: React.ReactNode;
  right?: boolean;
  strong?: boolean;
}) {
  return (
    <th
      className={`px-2.5 py-2 border-b border-zinc-200 ${
        right ? 'text-right' : 'text-left'
      } ${strong ? 'text-zinc-700 font-semibold' : 'font-medium'}`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  right,
  strong,
  tone,
}: {
  children: React.ReactNode;
  right?: boolean;
  strong?: boolean;
  tone?: 'good' | 'warn' | 'bad';
}) {
  const cls =
    tone === 'good'
      ? 'text-[color:var(--color-accent,#5f7d56)]'
      : tone === 'warn'
      ? 'text-amber-700'
      : tone === 'bad'
      ? 'text-rose-700'
      : strong
      ? 'text-zinc-900 font-medium'
      : 'text-zinc-700';
  return (
    <td className={`px-2.5 py-1.5 whitespace-nowrap ${right ? 'text-right' : 'text-left'} ${cls}`}>
      {children}
    </td>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded-md text-[11px] font-medium transition-colors ${
        active ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-500 hover:text-zinc-800'
      }`}
    >
      {children}
    </button>
  );
}

function CompositionBar({
  liquid,
  portfolio,
  realEstate,
  gold,
}: {
  liquid: number;
  portfolio: number;
  realEstate: number;
  gold: number;
}) {
  const total = liquid + portfolio + realEstate + gold;
  if (total <= 0) return <span className="text-zinc-300 text-[10px]">—</span>;
  const segs = [
    { v: liquid, color: '#a1a1aa', label: 'Cash' },
    { v: portfolio, color: 'var(--color-accent, #5f7d56)', label: 'Investments' },
    { v: realEstate, color: '#c4a878', label: 'Real estate' },
    { v: gold, color: '#d4b878', label: 'Gold' },
  ].filter((s) => s.v > 0);
  return (
    <div
      className="flex h-2 rounded-full overflow-hidden bg-zinc-100"
      title={segs.map((s) => `${s.label}: ${formatINR(s.v, { compact: true })}`).join(' · ')}
    >
      {segs.map((s, i) => (
        <div key={i} style={{ width: `${(s.v / total) * 100}%`, backgroundColor: s.color }} />
      ))}
    </div>
  );
}
