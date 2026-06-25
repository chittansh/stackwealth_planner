/**
 * Subtle two-line "Coming soon" chip. Used to flag work-in-progress surfaces
 * (currently the Scenarios tab + report section) that the SW Investment Team
 * will refine further. Deliberately understated — muted zinc, no accent colour.
 */
export function ComingSoonChip({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex flex-col items-start rounded-md border border-zinc-200 bg-zinc-50/70 px-2.5 py-1 leading-none ${className}`}
    >
      <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
        Coming soon
      </span>
      <span className="mt-0.5 text-[9px] leading-tight text-zinc-400">
        To be Further Refined with SW Investment Team
      </span>
    </span>
  );
}
