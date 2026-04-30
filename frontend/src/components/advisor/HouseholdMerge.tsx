'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';

type Row = { household_id: string; name: string; eligible: boolean; reason?: string };
type Preview = {
  parent_household_id: string;
  combined_assets: number;
  combined_income_monthly: number;
  combined_expenses_monthly: number;
  combined_goals_count: number;
};

export function HouseholdMerge() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`${BACKEND}/api/advisor/clients`)
      .then((r) => r.json())
      .then((j) =>
        setRows((j.rows ?? []).map((r: { household_id: string; name: string }) => ({ ...r, eligible: true }))),
      )
      .catch(() => setRows([]));
  }, []);

  const togglePick = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const runPreview = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${BACKEND}/api/household/preview`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ household_ids: picked }),
      });
      setPreview(await r.json());
    } finally {
      setBusy(false);
    }
  };

  const confirmMerge = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      const r = await fetch(`${BACKEND}/api/household/merge`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ household_ids: picked }),
      });
      const j = await r.json();
      if (j.parent_household_id) router.push(`/plan/${j.parent_household_id}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 rounded-xl border border-zinc-200 bg-white p-5">
        <h2 className="text-sm font-medium text-zinc-700 mb-3">Pick eligible clients</h2>
        <ul className="flex flex-col">
          {rows.length === 0 && <li className="text-sm text-zinc-400">No clients to merge.</li>}
          {rows.map((r) => (
            <li key={r.household_id} className="flex items-center justify-between border-b border-zinc-100 py-2 last:border-0">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={picked.includes(r.household_id)}
                  disabled={!r.eligible}
                  onChange={() => togglePick(r.household_id)}
                />
                <span>{r.name}</span>
                {!r.eligible && <span className="text-xs text-zinc-400">{r.reason}</span>}
              </label>
              <span className="text-xs text-zinc-400">{r.household_id.slice(0, 8)}</span>
            </li>
          ))}
        </ul>
        <div className="flex justify-end gap-2 mt-3">
          <button
            onClick={runPreview}
            disabled={picked.length < 2 || busy}
            className="text-xs px-3 py-1.5 rounded-md border border-zinc-200 hover:bg-zinc-50 disabled:opacity-50"
          >
            Preview merge
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <h2 className="text-sm font-medium text-zinc-700 mb-3">Preview</h2>
        {!preview ? (
          <p className="text-xs text-zinc-500">Pick at least two clients and click Preview.</p>
        ) : (
          <div className="flex flex-col gap-2 text-sm">
            <Row label="Combined assets" value={`₹${preview.combined_assets.toLocaleString()}`} />
            <Row label="Combined income / mo" value={`₹${preview.combined_income_monthly.toLocaleString()}`} />
            <Row label="Combined expenses / mo" value={`₹${preview.combined_expenses_monthly.toLocaleString()}`} />
            <Row label="Combined goals" value={String(preview.combined_goals_count)} />
            <button
              onClick={confirmMerge}
              disabled={busy}
              className="mt-3 text-xs px-3 py-2 rounded-md bg-zinc-900 text-white disabled:opacity-50"
            >
              Confirm merge
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-zinc-100 pb-1.5 last:border-0">
      <span className="text-zinc-500">{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
