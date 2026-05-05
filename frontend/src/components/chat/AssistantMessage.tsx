'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Sparkles } from 'lucide-react';

/**
 * Assistant messages follow the 3-part contract pinned in the system prompt:
 *   1. Lead sentence
 *   2. Bulleted list
 *   3. One-line projection delta
 *
 * Rendered as markdown inside a subtle white card with an accent rail on the
 * left, paired with a tiny sparkle marker above so the agent voice is
 * visually distinct from the user's lavender pill.
 */
export function AssistantMessage({ text }: { text: string }) {
  return (
    <div className="self-start w-full max-w-full min-w-0 flex flex-col gap-1">
      <div className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-zinc-400">
        <Sparkles size={10} className="text-[color:var(--color-accent)]" />
        Planner
      </div>
      <div className="rounded-2xl rounded-tl-md border border-zinc-200 bg-white px-3 py-2 shadow-[0_1px_0_rgba(0,0,0,0.02)] min-w-0 overflow-hidden">
        <div className="text-[13px] leading-relaxed min-w-0 break-words">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0 text-zinc-800">{children}</p>,
              ul: ({ children }) => <ul className="my-1.5 pl-4 list-disc marker:text-zinc-300 space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="my-1.5 pl-4 list-decimal marker:text-zinc-300 space-y-0.5">{children}</ol>,
              li: ({ children }) => <li className="text-zinc-700">{children}</li>,
              strong: ({ children }) => <strong className="font-semibold text-zinc-900">{children}</strong>,
              em: ({ children }) => <em className="italic text-zinc-700">{children}</em>,
              code: ({ children }) => (
                <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11.5px] text-zinc-800 break-all">
                  {children}
                </code>
              ),
              h1: ({ children }) => <h3 className="text-[13px] font-medium mt-2 mb-1 text-zinc-900">{children}</h3>,
              h2: ({ children }) => <h3 className="text-[13px] font-medium mt-2 mb-1 text-zinc-900">{children}</h3>,
              h3: ({ children }) => <h3 className="text-[13px] font-medium mt-2 mb-1 text-zinc-900">{children}</h3>,
              // Render HRs as breathing room, not a hard divider that reads as a card break.
              hr: () => <div className="h-1.5" aria-hidden />,
              a: ({ href, children }) => (
                <a href={href} className="text-[color:var(--color-accent)] underline" target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
              blockquote: ({ children }) => (
                <blockquote className="border-l-2 border-zinc-200 pl-2 text-zinc-600 italic">{children}</blockquote>
              ),
            }}
          >
            {text}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
