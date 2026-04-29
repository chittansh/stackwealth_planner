'use client';

import { Paperclip } from 'lucide-react';

export function MessageBubble({
  text,
  files,
}: {
  text?: string;
  files?: { name: string; size: number }[];
}) {
  return (
    <div className="self-start max-w-[260px] bg-zinc-100 rounded-2xl px-3 py-2 text-sm text-zinc-800 whitespace-pre-wrap">
      {text}
      {files && files.length > 0 && (
        <div className="mt-1.5 flex flex-col gap-1">
          {files.map((f) => (
            <div key={f.name} className="flex items-center gap-1.5 text-xs text-zinc-600 bg-white rounded-md px-2 py-1">
              <Paperclip size={11} />
              <span className="truncate">{f.name}</span>
              <span className="text-zinc-400 tabular-nums">{Math.round(f.size / 1024)}KB</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
