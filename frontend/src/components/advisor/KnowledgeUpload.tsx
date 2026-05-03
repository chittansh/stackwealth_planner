'use client';

import { useEffect, useState } from 'react';
import { Upload, FileText } from 'lucide-react';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:4000';
const ORG = 'main';

type Doc = { id: string; filename: string; uploaded_at: string; chunk_count: number };

export function KnowledgeUpload() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const r = await fetch(`${BACKEND}/api/knowledge/${ORG}`);
    const j = await r.json();
    setDocs(j.docs ?? []);
  };

  useEffect(() => {
    refresh().catch(() => undefined);
  }, []);

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append('file', f);
    try {
      await fetch(`${BACKEND}/api/knowledge/${ORG}`, { method: 'POST', body: fd });
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <label
        className="rounded-xl border border-dashed border-zinc-300 p-8 flex flex-col items-center justify-center text-sm text-zinc-500 cursor-pointer hover:border-zinc-400 lg:col-span-1"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          upload(e.dataTransfer.files);
        }}
      >
        <Upload size={20} className="mb-2 text-zinc-400" />
        Drop files or click to upload
        <input type="file" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
        {busy && <p className="mt-2 text-xs text-zinc-400">Indexing…</p>}
      </label>

      <div className="lg:col-span-2 rounded-xl border border-zinc-200 bg-white">
        <div className="px-5 py-3 border-b border-zinc-100 text-sm font-medium">Indexed documents</div>
        <ul>
          {docs.length === 0 ? (
            <li className="px-5 py-6 text-sm text-zinc-500">No documents indexed yet.</li>
          ) : (
            docs.map((d) => (
              <li key={d.id} className="flex items-center gap-2 px-5 py-2.5 border-b border-zinc-100 last:border-0 text-sm">
                <FileText size={14} className="text-zinc-400" />
                <span className="flex-1 truncate">{d.filename}</span>
                <span className="text-xs text-zinc-400 tabular-nums">{d.chunk_count} chunks</span>
                <span className="text-xs text-zinc-400">{new Date(d.uploaded_at).toLocaleString()}</span>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
