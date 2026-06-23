'use client';

import { useCallback, useEffect, useState } from 'react';

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type Sheet = { name: string; rows: string[][] };

/**
 * In-browser view of the firm's CFP workbook AFTER the backend has injected the
 * client's inputs and recalculated it headlessly with LibreOffice. The actual
 * computed sheets are rendered here as a grid — no desktop spreadsheet needed.
 * A download link is offered for the raw .xlsx.
 */
export function ComputedExcelView({ householdId }: { householdId: string }) {
  const [sheets, setSheets] = useState<Sheet[] | null>(null);
  const [active, setActive] = useState(0);
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [err, setErr] = useState<string>('');

  const load = useCallback(
    async (recompute: boolean) => {
      setState('loading');
      setErr('');
      try {
        if (recompute) {
          await fetch(`${BASE}/api/excel/${householdId}/compute`, { method: 'POST' });
        }
        const r = await fetch(`${BASE}/api/excel/${householdId}/grid`, { cache: 'no-store' });
        if (r.status === 404) {
          setState('empty');
          return;
        }
        if (!r.ok) throw new Error(`grid ${r.status}`);
        const j = await r.json();
        setSheets(j.sheets ?? []);
        setActive(0);
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

  if (state === 'loading') {
    return (
      <div className="rounded-xl border border-neutral-200 bg-white p-8 text-sm text-neutral-500">
        Recalculating the CFP workbook…
      </div>
    );
  }

  if (state === 'empty') {
    return (
      <div className="rounded-xl border border-neutral-200 bg-white p-8 text-sm text-neutral-600">
        No CFP input workbook uploaded yet. Upload the firm-template{' '}
        <span className="font-medium">.xlsx</span> for this household and the computed plan
        will appear here.
      </div>
    );
  }

  if (state === 'error') {
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
  }

  const sheet = sheets?.[active];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {sheets?.map((s, i) => (
            <button
              key={s.name}
              onClick={() => setActive(i)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                i === active
                  ? 'bg-neutral-900 text-white'
                  : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
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
            className="rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-100"
          >
            Download .xlsx
          </a>
        </div>
      </div>

      <div className="overflow-auto rounded-xl border border-neutral-200 bg-white max-h-[calc(100vh-220px)]">
        <table className="border-collapse text-xs">
          <tbody>
            {sheet?.rows.map((row, ri) => (
              <tr key={ri} className={ri === 0 ? 'bg-neutral-50' : ''}>
                {row.map((cell, ci) => {
                  const isNum = /^[-₹]?[\d,]+(\.\d+)?%?$/.test(cell.trim()) && cell.trim() !== '';
                  return (
                    <td
                      key={ci}
                      className={`border border-neutral-100 px-2 py-1 whitespace-nowrap ${
                        isNum ? 'text-right tabular-nums text-neutral-800' : 'text-neutral-700'
                      } ${ri === 0 ? 'font-semibold text-neutral-900' : ''}`}
                    >
                      {cell}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-neutral-400">
        Computed by the firm&apos;s CFP workbook (recalculated server-side). Values mirror the
        Excel model cell-for-cell.
      </p>
    </div>
  );
}
