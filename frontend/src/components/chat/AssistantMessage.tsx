'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Sparkles, ThumbsUp, ThumbsDown, Check, X } from 'lucide-react';
import { submitFeedback } from '@/lib/api';

/**
 * Assistant messages follow the 3-part contract pinned in the system prompt:
 *   1. Lead sentence
 *   2. Bulleted list
 *   3. One-line projection delta
 *
 * Rendered as markdown inside a subtle white card with an accent rail on the
 * left, paired with a tiny sparkle marker above so the agent voice is
 * visually distinct from the user's lavender pill.
 *
 * Feedback row: thumbs up/down under each message — when traceId is present
 * the click POSTs a Langfuse score against that trace + turn observation.
 * Optional comment box opens after the user picks thumbs-down.
 */
export function AssistantMessage({
  text,
  traceId,
  observationId,
  turn,
  feedback,
  feedbackComment,
  onFeedback,
}: {
  text: string;
  traceId?: string;
  observationId?: string;
  turn?: number;
  feedback?: 1 | -1;
  feedbackComment?: string;
  onFeedback?: (value: 1 | -1, comment?: string) => void;
}) {
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

      {traceId ? (
        <FeedbackRow
          traceId={traceId}
          observationId={observationId}
          turn={turn}
          feedback={feedback}
          feedbackComment={feedbackComment}
          onSubmit={onFeedback}
        />
      ) : null}
    </div>
  );
}

function FeedbackRow({
  traceId,
  observationId,
  turn,
  feedback,
  feedbackComment,
  onSubmit,
}: {
  traceId: string;
  observationId?: string;
  turn?: number;
  feedback?: 1 | -1;
  feedbackComment?: string;
  onSubmit?: (value: 1 | -1, comment?: string) => void;
}) {
  const [busy, setBusy] = useState<null | 1 | -1>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCommentBox, setShowCommentBox] = useState(false);
  const [comment, setComment] = useState('');

  const send = async (value: 1 | -1, withComment?: string) => {
    setBusy(value);
    setError(null);
    const r = await submitFeedback({
      trace_id: traceId,
      observation_id: observationId,
      value,
      comment: withComment,
      turn,
    });
    setBusy(null);
    if (!r.ok) {
      setError(r.error ?? 'Failed to submit feedback');
      return;
    }
    onSubmit?.(value, withComment);
  };

  // Already submitted — show the read-only state.
  if (feedback !== undefined) {
    return (
      <div className="inline-flex items-center gap-1.5 text-[10px] text-zinc-500 px-1">
        {feedback === 1 ? (
          <ThumbsUp size={11} className="text-emerald-600" />
        ) : (
          <ThumbsDown size={11} className="text-rose-600" />
        )}
        <span>Feedback recorded</span>
        {feedbackComment ? (
          <span className="text-zinc-400">— &ldquo;{feedbackComment}&rdquo;</span>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1 pl-1">
      <div className="inline-flex items-center gap-1 text-zinc-400">
        <button
          type="button"
          aria-label="Helpful"
          disabled={busy !== null}
          onClick={() => void send(1)}
          className={`w-6 h-6 grid place-items-center rounded-md transition-colors hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-50 ${
            busy === 1 ? 'text-emerald-600' : ''
          }`}
        >
          <ThumbsUp size={12} />
        </button>
        <button
          type="button"
          aria-label="Not helpful"
          disabled={busy !== null}
          onClick={() => setShowCommentBox(true)}
          className={`w-6 h-6 grid place-items-center rounded-md transition-colors hover:bg-rose-50 hover:text-rose-700 disabled:opacity-50 ${
            busy === -1 ? 'text-rose-600' : ''
          }`}
        >
          <ThumbsDown size={12} />
        </button>
        {error ? <span className="text-[10px] text-rose-600 ml-1">{error}</span> : null}
      </div>

      {showCommentBox ? (
        <div className="flex items-center gap-1 mt-0.5">
          <input
            type="text"
            autoFocus
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="What was off? (optional)"
            className="flex-1 text-[11px] px-2 py-1 rounded-md border border-zinc-200 bg-white text-zinc-700 placeholder:text-zinc-400 focus:outline-none focus:border-zinc-400"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                void send(-1, comment.trim() || undefined);
                setShowCommentBox(false);
              }
              if (e.key === 'Escape') {
                setShowCommentBox(false);
                setComment('');
              }
            }}
          />
          <button
            type="button"
            aria-label="Submit feedback"
            disabled={busy !== null}
            onClick={() => {
              void send(-1, comment.trim() || undefined);
              setShowCommentBox(false);
            }}
            className="w-6 h-6 grid place-items-center rounded-md text-zinc-500 hover:bg-rose-50 hover:text-rose-700"
          >
            <Check size={12} />
          </button>
          <button
            type="button"
            aria-label="Cancel"
            onClick={() => {
              setShowCommentBox(false);
              setComment('');
            }}
            className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:bg-zinc-50 hover:text-zinc-600"
          >
            <X size={12} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
