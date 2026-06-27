'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type Cell = { v: string; f: string | null; num: boolean };
type Row = { n: number; cells: Cell[] };
type Freeze = { rows: number; cols: number };
type Sheet = { name: string; cols: string[]; rows: Row[]; freeze?: Freeze };
type Selected = { r: number; c: number } | null;

// Frozen-pane geometry. Heights/widths are fixed so the sticky offsets for the
// stacked header rows line up exactly.
const GUTTER_H = 26; // column-letter header row
const ROW_H = 26; // a frozen header data row
const ROWNUM_W = 48; // row-number gutter column (w-12)

/**
 * In-browser view of the firm's CFP workbook after the backend injects the
 * client's inputs and recalculates it headlessly. Renders the computed sheets
 * as an Excel-like grid: column letters, row numbers, cell selection and a
 * formula bar that reveals the calculation behind any cell — no desktop app.
 */
export function ComputedExcelView({ householdId }: { householdId: string }) {
  const [sheets, setSheets] = useState<Sheet[] | null>(null);
  const [active, setActive] = useState(0);
  const [sel, setSel] = useState<Selected>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [err, setErr] = useState('');
  const gridRef = useRef<HTMLDivElement>(null);

  const load = useCallback(
    async (recompute: boolean) => {
      setState('loading');
      setErr('');
      try {
        if (recompute) await fetch(`${BASE}/api/excel/${householdId}/compute`, { method: 'POST' });
        const r = await fetch(`${BASE}/api/excel/${householdId}/grid`, { cache: 'no-store' });
        if (r.status === 404) return setState('empty');
        if (!r.ok) throw new Error(`grid ${r.status}`);
        const j = await r.json();
        setSheets(j.sheets ?? []);
        setActive(0);
        setSel(null);
        setState('ready');
      } catch (e) {
        setErr(String(e));
        setState('error');
      }
    },
    [householdId],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const sheet = sheets?.[active];
  const freezeRows = sheet?.freeze?.rows ?? 0;
  const freezeCols = sheet?.freeze?.cols ?? 0;
  const selCell = useMemo<Cell | null>(() => {
    if (!sheet || !sel) return null;
    return sheet.rows[sel.r]?.cells[sel.c] ?? null;
  }, [sheet, sel]);
  const selAddr = useMemo(() => {
    if (!sheet || !sel) return '';
    return `${sheet.cols[sel.c] ?? ''}${sheet.rows[sel.r]?.n ?? ''}`;
  }, [sheet, sel]);

  // Arrow-key navigation, Excel-style.
  const onKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sheet || !sel) return;
      const maxR = sheet.rows.length - 1;
      const maxC = sheet.cols.length - 1;
      let { r, c } = sel;
      if (e.key === 'ArrowDown') r = Math.min(maxR, r + 1);
      else if (e.key === 'ArrowUp') r = Math.max(0, r - 1);
      else if (e.key === 'ArrowRight') c = Math.min(maxC, c + 1);
      else if (e.key === 'ArrowLeft') c = Math.max(0, c - 1);
      else return;
      e.preventDefault();
      setSel({ r, c });
    },
    [sheet, sel],
  );

  if (state === 'loading')
    return <Shell>Recalculating the CFP workbook…</Shell>;
  if (state === 'empty')
    return (
      <Shell>
        No CFP input workbook uploaded yet. Upload the firm-template{' '}
        <span className="font-medium">.xlsx</span> for this household and the computed plan will
        appear here.
      </Shell>
    );
  if (state === 'error')
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Could not load the computed workbook: {err}
        <button
          onClick={() => void load(false)}
          className="ml-3 rounded-md border border-red-300 px-2 py-1 text-xs hover:bg-red-100"
        >
          Retry
        </button>
      </div>
    );

  return (
    <div className="flex flex-col gap-2">
      {/* Toolbar: sheet tabs + actions */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1">
          {sheets?.map((s, i) => (
            <button
              key={s.name}
              onClick={() => {
                setActive(i);
                setSel(null);
              }}
              className={`rounded-t-md border-b-2 px-3 py-1.5 text-xs font-medium transition ${
                i === active
                  ? 'border-emerald-500 bg-white text-neutral-900'
                  : 'border-transparent text-neutral-500 hover:bg-neutral-100 hover:text-neutral-700'
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void load(true)}
            className="rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-100"
          >
            Recalculate
          </button>
          <a
            href={`${BASE}/api/excel/${householdId}.xlsx`}
            className="rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700"
          >
            Download .xlsx
          </a>
        </div>
      </div>

      {/* Formula bar */}
      <div className="flex items-stretch overflow-hidden rounded-lg border border-neutral-200 bg-white text-xs">
        <div className="flex w-16 shrink-0 items-center justify-center border-r border-neutral-200 bg-neutral-50 font-mono font-semibold text-neutral-600">
          {selAddr || '—'}
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 font-mono text-neutral-700">
          <span className="select-none italic text-neutral-400">fx</span>
          {selCell ? (
            selCell.f ? (
              <span className="text-emerald-700">{selCell.f}</span>
            ) : (
              <span className="text-neutral-600">{selCell.v || <em className="text-neutral-300">empty</em>}</span>
            )
          ) : (
            <span className="text-neutral-300">select a cell to see its calculation</span>
          )}
        </div>
        {selCell?.f && (
          <div className="ml-auto flex items-center px-3 text-neutral-400">
            = <span className="ml-1 font-mono font-medium text-neutral-700">{selCell.v}</span>
          </div>
        )}
      </div>

      {/* Grid */}
      <div
        ref={gridRef}
        tabIndex={0}
        onKeyDown={onKey}
        className="overflow-auto rounded-lg border border-neutral-200 bg-white outline-none max-h-[calc(100vh-260px)]"
      >
        <table className="border-separate border-spacing-0 text-xs">
          <thead>
            <tr>
              <th
                style={{ height: GUTTER_H }}
                className="sticky left-0 top-0 z-50 w-12 border-b border-r border-neutral-300 bg-neutral-200"
              />
              {sheet?.cols.map((col, ci) => (
                <th
                  key={ci}
                  style={{ height: GUTTER_H }}
                  className={`sticky top-0 z-40 min-w-[84px] border-b border-r border-neutral-300 px-2 text-center text-[11px] font-semibold ${
                    sel?.c === ci ? 'bg-emerald-100 text-emerald-800' : 'bg-neutral-100 text-neutral-500'
                  }`}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sheet?.rows.map((row, ri) => {
              const frozenRow = ri < freezeRows;
              const rowTop = frozenRow ? GUTTER_H + ri * ROW_H : undefined;
              return (
                <tr key={ri}>
                  <td
                    style={{ position: 'sticky', left: 0, top: rowTop, height: frozenRow ? ROW_H : undefined, zIndex: frozenRow ? 45 : 30 }}
                    className={`w-12 border-b border-r border-neutral-300 px-1 text-center text-[11px] font-semibold ${
                      sel?.r === ri ? 'bg-emerald-100 text-emerald-800' : 'bg-neutral-100 text-neutral-400'
                    }`}
                  >
                    {row.n}
                  </td>
                  {row.cells.map((cell, ci) => {
                    const frozenCol = ci < freezeCols;
                    const selected = sel?.r === ri && sel?.c === ci;
                    const sticky = frozenRow || frozenCol;
                    const style: React.CSSProperties = {};
                    if (sticky) style.position = 'sticky';
                    if (frozenRow) {
                      style.top = rowTop;
                      style.height = ROW_H;
                    }
                    if (frozenCol) style.left = ROWNUM_W;
                    if (frozenRow && frozenCol) style.zIndex = 35;
                    else if (frozenRow) style.zIndex = 25;
                    else if (frozenCol) style.zIndex = 15;
                    // Frozen cells need an OPAQUE background so scrolled content
                    // doesn't bleed through; header rows read as headers.
                    const frozenBg = frozenRow
                      ? 'bg-neutral-100 font-medium'
                      : frozenCol
                        ? 'bg-white'
                        : cell.f
                          ? 'bg-emerald-50/40'
                          : '';
                    return (
                      <td
                        key={ci}
                        style={style}
                        onClick={() => setSel({ r: ri, c: ci })}
                        title={cell.f ?? undefined}
                        className={`cursor-cell whitespace-nowrap border-b border-r border-neutral-100 px-2 py-1 ${
                          cell.num ? 'text-right tabular-nums text-neutral-800' : 'text-neutral-700'
                        } ${frozenBg} ${
                          selected ? 'outline outline-2 -outline-offset-2 outline-emerald-500 bg-emerald-50' : sticky ? '' : 'hover:bg-neutral-50'
                        }`}
                      >
                        {cell.v}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-neutral-400">
        Computed by the firm&apos;s CFP workbook, recalculated server-side. Click any cell to see
        its formula. <span className="rounded bg-emerald-50 px-1 text-emerald-600">Green</span> cells
        are calculated; the rest are inputs.
      </p>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-8 text-sm text-neutral-600">
      {children}
    </div>
  );
}
