'use client';

/**
 * Assistant messages follow the 3-part contract pinned in the system prompt:
 *   1. Lead sentence
 *   2. Bulleted list
 *   3. One-line projection delta
 * Render as plain text (no bubble) with bullet styling for `- ` lines.
 */
export function AssistantMessage({ text }: { text: string }) {
  const lines = text.split('\n');
  return (
    <div className="self-start max-w-[260px] text-sm text-zinc-800 leading-relaxed flex flex-col gap-1">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith('-') || trimmed.startsWith('•')) {
          return (
            <div key={i} className="pl-3 text-zinc-700">
              <span className="text-zinc-400">•</span> {trimmed.replace(/^[-•]\s?/, '')}
            </div>
          );
        }
        return (
          <p key={i} className="text-zinc-800">
            {line}
          </p>
        );
      })}
    </div>
  );
}
