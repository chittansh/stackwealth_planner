'use client';

import { Sparkles } from 'lucide-react';

/**
 * Thinking indicator — visible the moment the user hits send and removed when
 * the first tool call or assistant message lands. Sits in the same column as
 * the assistant bubble for visual continuity.
 */
export function ThinkingDots() {
  return (
    <div className="self-start max-w-[280px] flex flex-col gap-1">
      <div className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-zinc-400">
        <Sparkles size={10} className="text-[color:var(--color-accent)]" />
        Planner
      </div>
      <div className="rounded-2xl rounded-tl-md border border-zinc-200 bg-white px-3 py-2.5">
        <span className="inline-flex items-center gap-1.5 text-zinc-400 text-xs">
          <span className="dot" />
          <span className="dot" style={{ animationDelay: '0.15s' }} />
          <span className="dot" style={{ animationDelay: '0.3s' }} />
          <span className="ml-1.5 italic">thinking</span>
        </span>
      </div>
      <style>{`
        .dot {
          width: 5px;
          height: 5px;
          border-radius: 9999px;
          background: currentColor;
          display: inline-block;
          animation: sw-bounce 1.1s infinite ease-in-out both;
        }
        @keyframes sw-bounce {
          0%, 80%, 100% { transform: scale(0.5); opacity: 0.4; }
          40% { transform: scale(1); opacity: 1; }
        }
      `}</style>
    </div>
  );
}
