'use client';

import { useState, useRef, useCallback } from 'react';
import { Paperclip, Mic, ArrowUp } from 'lucide-react';

export function AskInput({
  onSend,
  disabled,
}: {
  onSend: (text: string, files: File[]) => void | Promise<void>;
  disabled?: boolean;
}) {
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = useCallback(() => {
    if (disabled) return;
    if (!text.trim() && files.length === 0) return;
    void onSend(text.trim(), files);
    setText('');
    setFiles([]);
  }, [text, files, onSend, disabled]);

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData.files;
    if (items && items.length) {
      setFiles((prev) => [...prev, ...Array.from(items)]);
    }
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files ?? []);
    if (dropped.length) setFiles((p) => [...p, ...dropped]);
  };

  return (
    <div
      className="flex flex-col gap-2 rounded-xl border border-zinc-200 px-2 py-1.5 focus-within:border-zinc-400"
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {files.map((f, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 text-xs bg-zinc-100 px-2 py-0.5 rounded-md"
            >
              <Paperclip size={10} /> {f.name}
              <button onClick={() => setFiles((p) => p.filter((_, j) => j !== i))} className="text-zinc-400 hover:text-zinc-700">×</button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-1">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="w-7 h-7 grid place-items-center rounded-md text-zinc-400 hover:bg-zinc-50"
          title="Attach files"
        >
          <Paperclip size={14} />
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            const list = Array.from(e.target.files ?? []);
            if (list.length) setFiles((p) => [...p, ...list]);
            e.target.value = '';
          }}
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          onPaste={onPaste}
          rows={1}
          placeholder="Ask anything…"
          className="flex-1 resize-none bg-transparent outline-none text-sm py-1 max-h-24"
          disabled={disabled}
        />
        <button
          type="button"
          className="w-7 h-7 grid place-items-center rounded-md text-zinc-400 hover:bg-zinc-50"
          title="Record audio"
        >
          <Mic size={14} />
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={disabled || (!text.trim() && files.length === 0)}
          className="w-7 h-7 grid place-items-center rounded-md bg-zinc-900 text-white disabled:opacity-30"
          title="Send"
        >
          <ArrowUp size={14} />
        </button>
      </div>
    </div>
  );
}
