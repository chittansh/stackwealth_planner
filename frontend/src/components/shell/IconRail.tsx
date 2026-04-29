'use client';

import { Home, Search, MessageSquare, FileText, Sliders, Sparkles, Settings } from 'lucide-react';

export function IconRail({ householdId: _ }: { householdId: string }) {
  const icons = [
    { Icon: Home, label: 'Home' },
    { Icon: Search, label: 'Search' },
    { Icon: MessageSquare, label: 'Chats' },
    { Icon: FileText, label: 'Plans' },
    { Icon: Sliders, label: 'Scenarios' },
    { Icon: Sparkles, label: 'Highlights' },
  ];
  return (
    <aside className="w-[52px] shrink-0 bg-zinc-950 text-zinc-300 flex flex-col items-center py-3 gap-3">
      <div className="w-7 h-7 rounded-md bg-zinc-100 text-zinc-900 flex items-center justify-center font-bold text-xs">SW</div>
      <div className="mt-3 flex flex-col gap-1">
        {icons.map(({ Icon, label }) => (
          <button key={label} title={label} className="w-9 h-9 rounded-md hover:bg-zinc-800 grid place-items-center">
            <Icon size={16} />
          </button>
        ))}
      </div>
      <div className="mt-auto">
        <button title="Settings" className="w-9 h-9 rounded-md hover:bg-zinc-800 grid place-items-center">
          <Settings size={16} />
        </button>
      </div>
    </aside>
  );
}
