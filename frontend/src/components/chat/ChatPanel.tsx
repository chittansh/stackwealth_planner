'use client';

import { useState, useCallback, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import { StatusPill } from './StatusPill';
import { AssistantMessage } from './AssistantMessage';
import { AskInput } from './AskInput';
import { streamChat, uploadFiles, uploadText } from '@/lib/api';
import { Sparkles, ListTodo } from 'lucide-react';

type Msg =
  | { kind: 'user'; text: string; files?: { name: string; size: number }[] }
  | { kind: 'status'; text: string }
  | { kind: 'assistant'; text: string };

type Mode = 'chat' | 'topics';

const PLANNING_TOPICS = [
  'Financial independence',
  'Life changes',
  'Buying property',
  'Retirement planning',
  'Optimization',
  'Scenarios',
  'Plan tools',
];

export function ChatPanel({ householdId }: { householdId: string }) {
  const [mode, setMode] = useState<Mode>('chat');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleSend = useCallback(
    async (text: string, attachments: File[]) => {
      if (!text && attachments.length === 0) return;
      setBusy(true);
      const userMsg: Msg = {
        kind: 'user',
        text,
        files: attachments.map((f) => ({ name: f.name, size: f.size })),
      };
      setMessages((m) => [...m, userMsg]);

      // Upload any attachments first.
      if (attachments.length) {
        setMessages((m) => [...m, { kind: 'status', text: 'Reading attachments…' }]);
        try {
          await uploadFiles(householdId, attachments);
        } catch {
          setMessages((m) => [...m, { kind: 'status', text: 'Upload failed.' }]);
        }
      }

      // Treat plain text > 200 chars as a transcript-like extraction too.
      if (text && attachments.length === 0 && text.length > 200) {
        setMessages((m) => [...m, { kind: 'status', text: 'Extracting from your note…' }]);
        try {
          await uploadText(householdId, text, 'user');
        } catch {
          /* fall through to chat */
        }
      }

      // Stream the agent's response.
      try {
        for await (const ev of streamChat(householdId, text)) {
          if (ev.event === 'tool_call') {
            const name = (ev.data as { name: string }).name;
            setMessages((m) => [...m, { kind: 'status', text: `${humanizeTool(name)}…` }]);
          } else if (ev.event === 'message') {
            const reply = (ev.data as { text: string }).text;
            setMessages((m) => [...m, { kind: 'assistant', text: reply }]);
          } else if (ev.event === 'error') {
            setMessages((m) => [...m, { kind: 'assistant', text: 'Something went wrong. Try again.' }]);
          }
        }
      } catch {
        setMessages((m) => [...m, { kind: 'assistant', text: 'Network error.' }]);
      } finally {
        setBusy(false);
        requestAnimationFrame(() => {
          containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' });
        });
      }
    },
    [householdId],
  );

  return (
    <aside className="w-[300px] shrink-0 border-r border-zinc-200 flex flex-col bg-white">
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
      </div>

      {mode === 'topics' ? (
        <div className="p-3 text-sm text-zinc-700">
          <div className="text-xs text-zinc-400 uppercase tracking-wide mb-2">Planning topics</div>
          <ul className="flex flex-col">
            {PLANNING_TOPICS.map((t) => (
              <li key={t}>
                <button
                  onClick={() => {
                    setMode('chat');
                    void handleSend(`Tell me about ${t}`, []);
                  }}
                  className="w-full text-left px-2 py-1.5 rounded-md hover:bg-zinc-50"
                >
                  {t}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div ref={containerRef} className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
          {messages.length === 0 && (
            <p className="text-sm text-zinc-500">
              Drop a PDF / Excel / CSV / image / audio file or paste a note. I’ll extract what I can and ask only for what’s missing.
            </p>
          )}
          {messages.map((m, i) => {
            if (m.kind === 'user') return <MessageBubble key={i} text={m.text} files={m.files} />;
            if (m.kind === 'status') return <StatusPill key={i} text={m.text} />;
            return <AssistantMessage key={i} text={m.text} />;
          })}
        </div>
      )}

      <div className="p-3 border-t border-zinc-200">
        <AskInput onSend={handleSend} disabled={busy} />
      </div>
    </aside>
  );
}

function humanizeTool(name: string): string {
  const map: Record<string, string> = {
    'intake.ingest': 'Reading your file',
    'intake.confirm': 'Confirming a value',
    'plan.set': 'Updating plan',
    'plan.add': 'Adding a row',
    'plan.remove': 'Removing a row',
    'plan.assumption': 'Updating assumptions',
    'risk.assess': 'Assessing risk',
    'allocate.recommend': 'Recommending allocation',
    'freedom.score': 'Computing freedom score',
    'tax.harvest': 'Computing tax view',
    'cashflow.project': 'Projecting cash flow',
    'scenario.pin': 'Pinning scenario',
    'scenario.diff': 'Comparing scenarios',
    'montecarlo.run': 'Running Monte Carlo',
    'knowledge.retrieve': 'Looking up knowledge base',
    'news.relevance': 'Scoring news relevance',
  };
  return map[name] ?? name;
}
