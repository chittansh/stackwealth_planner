'use client';

export function StatusPill({ text }: { text: string }) {
  return (
    <div className="self-start inline-flex items-center gap-1.5 bg-zinc-50 text-zinc-500 italic text-xs px-2 py-1 rounded-md border border-zinc-100">
      <Spinner />
      {text}
    </div>
  );
}

function Spinner() {
  return (
    <svg width={10} height={10} viewBox="0 0 24 24" className="animate-spin">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="40 60" fill="none" />
    </svg>
  );
}
