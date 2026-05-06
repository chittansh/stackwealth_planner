'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { MessageBubble } from './MessageBubble';
import { StatusPill } from './StatusPill';
import { ThinkingDots } from './ThinkingDots';
import { ToolGroup, type GroupedTool } from './ToolGroup';
import { AssistantMessage } from './AssistantMessage';
import { AskInput } from './AskInput';
import { RiskGate } from './RiskGate';
import { ChatSwitcher } from './ChatSwitcher';
import { streamChat, uploadFiles, resetChat, hydrateChat } from '@/lib/api';
import { firePlanChanged } from '@/lib/prompt';
import { Sparkles, ListTodo, Plus } from 'lucide-react';
import { useChatStore, type StoredMsg } from '@/lib/chatStore';

type ToolMsg = {
  kind: 'tool';
  id: string;
  name: string;
  args: unknown;
  result?: unknown;
  state: 'running' | 'done' | 'error';
};

type AssistantMsg = {
  kind: 'assistant';
  text: string;
  traceId?: string;
  observationId?: string;
  turn?: number;
  feedback?: 1 | -1;
  feedbackComment?: string;
};

type Msg =
  | { kind: 'user'; text: string; files?: { name: string; size: number }[] }
  | { kind: 'status'; text: string; tag?: string; done?: boolean; error?: boolean }
  | { kind: 'thinking' }
  | ToolMsg
  | AssistantMsg
  | { kind: 'risk_gate' };

// Drop any in-flight "thinking" pills before appending the next event — once
// a tool_call or assistant message lands, the generic spinner is obsolete.
const replaceThinking = (m: Msg[], next: Msg): Msg[] => [...m.filter((x) => x.kind !== 'thinking'), next];

// Replace any status pill carrying the same `tag` (e.g. drop the in-flight
// "Reading attachments…" once the terminal "Extracted N fields" lands).
const replaceTaggedStatus = (m: Msg[], tag: string, next: Msg): Msg[] => [
  ...m.filter((x) => !(x.kind === 'status' && x.tag === tag)),
  next,
];

// The store keeps StoredMsg shape (one union with all optional fields).
// Cast safely — every Msg is a structural subset of StoredMsg.
const toStored = (m: Msg): StoredMsg => m as StoredMsg;
const fromStored = (m: StoredMsg): Msg => m as Msg;

type Mode = 'chat' | 'topics';

const PLANNING_TOPICS: { label: string; prompt: string }[] = [
  {
    label: 'Set up my plan',
    prompt: "Let's set up my plan from scratch — ask me what you need.",
  },
  {
    label: 'Add my income & expenses',
    prompt: "Help me capture my monthly income and recurring expenses.",
  },
  {
    label: 'Add a financial goal',
    prompt: "I want to add a financial goal — walk me through it.",
  },
  {
    label: 'Compute my Freedom Score',
    prompt: "Compute my Freedom Score and tell me what's holding me back.",
  },
  {
    label: 'Set my risk profile',
    prompt: 'Run the 3-question risk profile.',
  },
  {
    label: 'Recommend an allocation',
    prompt: 'Recommend an asset allocation for me.',
  },
  {
    label: 'Compare scenarios (Plan A vs Plan B)',
    prompt: 'What if I retire 5 years later? Pin it as Plan B and compare.',
  },
  {
    label: 'Run Monte Carlo',
    prompt: 'Run a Monte Carlo simulation and tell me the P10/P50/P90 freedom age.',
  },
  {
    label: 'Tax harvest review',
    prompt: 'Review my LTCG/STCG tax harvesting opportunities for this FY.',
  },
];

export function ChatPanel({ householdId }: { householdId: string }) {
  const [mode, setMode] = useState<Mode>('chat');
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const store = useChatStore(householdId);
  const messages: Msg[] = store.messages.map(fromStored);
  const setMessages = useCallback(
    (updater: (prev: Msg[]) => Msg[]) => {
      store.setMessages((prev) => updater(prev.map(fromStored)).map(toStored));
    },
    [store],
  );

  // Listen for top-bar / quick-add prompts dispatched from the shell.
  useEffect(() => {
    const onPrompt = (e: Event) => {
      const detail = (e as CustomEvent<{ prompt: string }>).detail;
      if (detail?.prompt) void handleSend(detail.prompt, []);
    };
    window.addEventListener('sw:chat-prompt', onPrompt as EventListener);
    return () => window.removeEventListener('sw:chat-prompt', onPrompt as EventListener);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [householdId, store.activeChatId]);

  // When the active chat changes (or first hydrates from localStorage), push
  // the prose history to the backend so the agent has context. Skip if the
  // chat is empty or contains only the in-flight thinking pill.
  useEffect(() => {
    if (!store.hydrated) return;
    const turns = store.messages
      .filter((m) => (m.kind === 'user' || m.kind === 'assistant') && typeof m.text === 'string' && m.text.trim())
      .map((m) => ({ role: m.kind as 'user' | 'assistant', text: m.text! }));
    if (turns.length === 0) return;
    void hydrateChat(householdId, store.activeChatId, turns).catch(() => undefined);
    // Only re-hydrate when the chat ID flips (or mounts) — not on every message.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [householdId, store.activeChatId, store.hydrated]);

  const handleSend = useCallback(
    async (text: string, attachments: File[]) => {
      if (!text && attachments.length === 0) return;
      setBusy(true);
      const userMsg: Msg = {
        kind: 'user',
        text,
        files: attachments.map((f) => ({ name: f.name, size: f.size })),
      };
      setMessages((m) => [...m, userMsg, { kind: 'thinking' }]);

      let uploadHint = '';
      let uploadFailedHard = false;
      if (attachments.length) {
        setMessages((m) =>
          replaceThinking(m, { kind: 'status', tag: 'upload', text: 'Reading attachments…' }),
        );
        try {
          const r = await uploadFiles(householdId, attachments);
          const summaries = r.summaries ?? [];
          uploadHint = summaries
            .map((s) =>
              s.error
                ? `• ${s.filename} — extraction FAILED: ${s.error}`
                : `• ${s.filename} (parser=${s.parser_used}) — ${s.fields_extracted} field(s) extracted across [${s.sections_set.join(', ') || '—'}]; missing: ${s.missing.length ? s.missing.join(', ') : 'none'}`,
            )
            .join('\n');
          const totalFields = summaries.reduce((n, s) => n + s.fields_extracted, 0);
          const failed = summaries.some((s) => s.error || s.fields_extracted === 0);
          uploadFailedHard = totalFields === 0;
          if (totalFields > 0) firePlanChanged();
          // Replace the in-flight pill with the terminal one — don't stack.
          setMessages((m) =>
            replaceTaggedStatus(m, 'upload', {
              kind: 'status',
              tag: 'upload',
              done: !uploadFailedHard,
              error: uploadFailedHard,
              text: totalFields
                ? `Extracted ${totalFields} field${totalFields === 1 ? '' : 's'} from ${summaries.length} file${summaries.length === 1 ? '' : 's'}`
                : failed
                ? `Could not extract from ${summaries.length} file${summaries.length === 1 ? '' : 's'}. Re-export as JPEG / PNG / PDF / CSV and try again.`
                : 'Upload processed (no fields extracted)',
            }),
          );
        } catch (err) {
          uploadFailedHard = true;
          setMessages((m) =>
            replaceTaggedStatus(m, 'upload', {
              kind: 'status',
              tag: 'upload',
              error: true,
              text: `Upload failed: ${(err as Error).message}`,
            }),
          );
        }
        setMessages((m) => [...m, { kind: 'thinking' }]);
      }

      // ALWAYS append the upload context to the agent message when attachments
      // exist — even if the user typed text. Otherwise the agent has no idea
      // any extraction happened.
      const uploadContext = attachments.length
        ? `\n\n[Uploaded files (already processed by the intake pipeline — DO NOT re-call intake_ingest):\n${uploadHint || '(no extraction summary available)'}\n\nWhat changed in PlanState is reflected in the snapshot above. Narrate it briefly and ask only for what's still missing. If extraction failed for a file, tell the user and suggest a workable alternative format.]`
        : '';
      const finalText = text
        ? `${text}${uploadContext}`
        : attachments.length
        ? `I uploaded ${attachments.length} file${attachments.length > 1 ? 's' : ''}.${uploadContext}`
        : '';
      void uploadFailedHard; // reserved for future UX hooks

      // Captured from the 'trace' SSE event and stamped onto the next
      // assistant message so the feedback UI knows which trace/observation
      // to score.
      let pendingTrace: { traceId?: string; observationId?: string; turn?: number } = {};

      try {
        for await (const ev of streamChat(householdId, finalText, store.activeChatId)) {
          if (ev.event === 'tool_call') {
            const data = ev.data as { id: string; name: string; args: unknown };
            setMessages((m) =>
              replaceThinking(m, {
                kind: 'tool',
                id: data.id,
                name: data.name,
                args: data.args,
                state: 'running',
              }),
            );
          } else if (ev.event === 'tool_result') {
            const data = ev.data as { id: string; name: string; result: unknown };
            const errored =
              data.result &&
              typeof data.result === 'object' &&
              'error' in (data.result as Record<string, unknown>);
            setMessages((m) =>
              m.map((x) =>
                x.kind === 'tool' && x.id === data.id
                  ? { ...x, result: data.result, state: errored ? 'error' : 'done' }
                  : x,
              ),
            );
            // Each tool result mutates the plan — push canvas to refresh now.
            firePlanChanged();
          } else if (ev.event === 'trace') {
            const d = ev.data as { trace_id: string; observation_id?: string; turn?: number };
            pendingTrace = {
              traceId: d.trace_id,
              observationId: d.observation_id,
              turn: d.turn,
            };
          } else if (ev.event === 'message') {
            const reply = (ev.data as { text: string }).text;
            const stamp = pendingTrace;
            pendingTrace = {};
            setMessages((m) =>
              replaceThinking(m, {
                kind: 'assistant',
                text: reply,
                traceId: stamp.traceId,
                observationId: stamp.observationId,
                turn: stamp.turn,
              }),
            );
          } else if (ev.event === 'error') {
            setMessages((m) =>
              replaceThinking(m, { kind: 'assistant', text: 'Something went wrong. Try again.' }),
            );
          }
        }
      } catch {
        setMessages((m) => replaceThinking(m, { kind: 'assistant', text: 'Network error.' }));
      } finally {
        // Make sure no orphan "thinking" pill is left behind on early returns.
        setMessages((m) => m.filter((x) => x.kind !== 'thinking'));
        setBusy(false);
        requestAnimationFrame(() => {
          containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' });
        });
      }
    },
    [householdId, store.activeChatId, setMessages],
  );

  const onDragOver = useCallback((e: React.DragEvent<HTMLElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    setDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent<HTMLElement>) => {
    if (e.currentTarget === e.target) setDragging(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLElement>) => {
      e.preventDefault();
      setDragging(false);
      const dropped = Array.from(e.dataTransfer.files ?? []);
      if (!dropped.length) return;
      // Fire upload immediately — these are intake artifacts, not chat-bound
      // attachments waiting for a Send.
      void handleSend('', dropped).catch(() => undefined);
    },
    [handleSend],
  );

  return (
    <aside
      className={`relative w-[300px] shrink-0 border-r border-zinc-200 flex flex-col bg-white ${
        dragging ? 'ring-2 ring-[color:var(--color-accent)] ring-inset' : ''
      }`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-0 bg-[color:var(--color-accent)]/5 grid place-items-center text-xs text-[color:var(--color-accent)] z-20">
          Drop to attach — PDF · XLSX · CSV · DOCX · MD · image · audio
        </div>
      )}
      <div className="h-14 px-4 flex items-center gap-2 border-b border-zinc-200">
        <button
          onClick={() => setMode('chat')}
          className={`text-xs px-2 py-1 rounded-md ${mode === 'chat' ? 'bg-zinc-100' : 'text-zinc-500'}`}
        >
          <Sparkles size={12} className="inline mr-1" /> Chat
        </button>
        <button
          onClick={() => setMode('topics')}
          className={`text-xs px-2 py-1 rounded-md ${mode === 'topics' ? 'bg-zinc-100' : 'text-zinc-500'}`}
        >
          <ListTodo size={12} className="inline mr-1" /> Topics
        </button>
        <div className="ml-auto flex items-center gap-1">
          <ChatSwitcher
            chats={store.chatList}
            activeId={store.activeChatId}
            onPick={(id) => store.switchChat(id)}
            onDelete={async (id) => {
              await resetChat(householdId, id).catch(() => undefined);
              store.deleteChat(id);
            }}
          />
          <button
            onClick={() => {
              if (busy) return;
              store.newChat();
            }}
            title="Start a new chat"
            className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
          >
            <Plus size={13} />
          </button>
        </div>
      </div>

      {mode === 'topics' ? (
        <div className="p-3 text-sm text-zinc-700">
          <div className="text-xs text-zinc-400 uppercase tracking-wide mb-2">Quick prompts</div>
          <ul className="flex flex-col">
            {PLANNING_TOPICS.map((t) => (
              <li key={t.label}>
                <button
                  onClick={() => {
                    setMode('chat');
                    void handleSend(t.prompt, []);
                  }}
                  className="w-full text-left px-2 py-1.5 rounded-md hover:bg-zinc-50 text-zinc-700"
                >
                  {t.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div ref={containerRef} className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
          {store.hydrated && messages.length === 0 && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-zinc-700">Two ways to start:</p>
              <ol className="text-[13px] text-zinc-600 space-y-1.5 list-decimal list-inside">
                <li>
                  <span className="text-zinc-800">Drop a doc</span> — PDF, Excel, CSV, image, or audio note.
                  I&apos;ll extract what I can and ask only for what&apos;s missing.
                </li>
                <li>
                  <span className="text-zinc-800">Just chat</span> — type your details (age, income,
                  expenses, goals) and I&apos;ll fill the plan as we go.
                </li>
              </ol>
              <button
                onClick={() => void handleSend("Let's set up my plan from scratch — ask me what you need.", [])}
                className="self-start text-xs px-3 py-1.5 rounded-md text-white"
                style={{ background: 'var(--color-accent)' }}
              >
                Start from scratch
              </button>
            </div>
          )}
          {renderMessages(messages, householdId, setMessages)}
        </div>
      )}

      <div className="p-3 border-t border-zinc-200">
        <AskInput onSend={handleSend} disabled={busy} />
      </div>
    </aside>
  );
}

/**
 * Walk the message list and fold any run of consecutive tool messages into a
 * single ToolGroup, leaving everything else as-is.
 */
function renderMessages(
  messages: Msg[],
  householdId: string,
  setMessages: (updater: (prev: Msg[]) => Msg[]) => void,
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    if (m.kind === 'tool') {
      // Collect every consecutive tool message into one group.
      const group: GroupedTool[] = [];
      const startIdx = i;
      while (i < messages.length && messages[i].kind === 'tool') {
        const t = messages[i] as ToolMsg;
        group.push({ id: t.id, name: t.name, args: t.args, result: t.result, state: t.state });
        i++;
      }
      out.push(<ToolGroup key={`group-${startIdx}`} tools={group} />);
      continue;
    }
    if (m.kind === 'user') out.push(<MessageBubble key={i} text={m.text} files={m.files} />);
    else if (m.kind === 'status')
      out.push(<StatusPill key={i} text={m.text} done={m.done} error={m.error} />);
    else if (m.kind === 'thinking') out.push(<ThinkingDots key={i} />);
    else if (m.kind === 'assistant') {
      const idx = i;
      out.push(
        <AssistantMessage
          key={i}
          text={m.text}
          traceId={m.traceId}
          observationId={m.observationId}
          turn={m.turn}
          feedback={m.feedback}
          feedbackComment={m.feedbackComment}
          onFeedback={(value, comment) =>
            setMessages((mm) =>
              mm.map((x, j) =>
                j === idx && x.kind === 'assistant'
                  ? { ...x, feedback: value, feedbackComment: comment }
                  : x,
              ),
            )
          }
        />,
      );
    }
    else if (m.kind === 'risk_gate') {
      out.push(
        <RiskGate
          key={i}
          householdId={householdId}
          onComplete={() =>
            setMessages((mm) => [
              ...mm,
              {
                kind: 'assistant',
                text: 'Risk profile computed. Allocation, tax, and Monte Carlo are now unlocked.',
              },
            ])
          }
        />,
      );
    }
    i++;
  }
  return out;
}

