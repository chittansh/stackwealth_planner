'use client';

import { useEffect, useState } from 'react';

/**
 * Listens for `sw:toast` window events and shows a small bottom-center pill.
 * Auto-dismisses after a short delay. No state library, no portal — just one
 * mountpoint near the root of the app shell.
 */
export function Toast() {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const onToast = (e: Event) => {
      const detail = (e as CustomEvent<{ text: string }>).detail;
      if (!detail?.text) return;
      setText(detail.text);
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => setText(null), 2200);
    };
    window.addEventListener('sw:toast', onToast as EventListener);
    return () => {
      window.removeEventListener('sw:toast', onToast as EventListener);
      if (timer) clearTimeout(timer);
    };
  }, []);

  if (!text) return null;

  return (
    <div className="pointer-events-none fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
      <div className="px-3 py-1.5 rounded-md bg-zinc-900 text-white text-[12px] shadow-md">{text}</div>
    </div>
  );
}
