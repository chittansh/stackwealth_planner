'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Check } from 'lucide-react';

export type DropdownOption<T extends string | number> = {
  value: T;
  label: string;
  hint?: string;
};

/**
 * Compact monochrome popover dropdown. Replaces native <select> for visual
 * consistency. Click-outside + Escape to dismiss; ↑/↓/Enter for keyboard nav.
 */
export function Dropdown<T extends string | number>({
  value,
  options,
  onChange,
  className = '',
  align = 'left',
  width = 160,
}: {
  value: T;
  options: DropdownOption<T>[];
  onChange: (next: T) => void;
  className?: string;
  align?: 'left' | 'right';
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  const [hover, setHover] = useState<number>(() => Math.max(0, options.findIndex((o) => o.value === value)));
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const active = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setHover((h) => (h + 1) % options.length);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setHover((h) => (h - 1 + options.length) % options.length);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        onChange(options[hover].value);
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, hover, options, onChange]);

  return (
    <div className={`relative ${className}`} ref={ref}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          setHover(Math.max(0, options.findIndex((o) => o.value === value)));
        }}
        className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-md border border-zinc-200 bg-white text-sm text-zinc-700 hover:bg-zinc-50"
      >
        <span>{active?.label ?? '—'}</span>
        <ChevronDown size={13} className={`text-zinc-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className={`absolute z-30 mt-1 rounded-lg border border-zinc-200 bg-white shadow-md py-1 ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
          style={{ minWidth: width }}
        >
          {options.map((o, i) => {
            const isActive = o.value === value;
            return (
              <button
                key={String(o.value)}
                onMouseEnter={() => setHover(i)}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className={`w-full text-left px-2.5 py-1.5 text-[13px] flex items-center gap-2 ${
                  i === hover ? 'bg-zinc-50' : ''
                } ${isActive ? 'text-zinc-900' : 'text-zinc-700'}`}
              >
                <span className="flex-1 truncate">{o.label}</span>
                {o.hint && <span className="text-[10px] text-zinc-400">{o.hint}</span>}
                {isActive && <Check size={12} style={{ color: 'var(--color-accent)' }} className="shrink-0" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
