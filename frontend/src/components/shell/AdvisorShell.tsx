'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Users, Combine, BookOpen, Newspaper } from 'lucide-react';
import { IconRail } from './IconRail';
import { Toast } from '@/components/ui/Toast';

const NAV = [
  { href: '/advisor/clients', label: 'Clients', Icon: Users },
  { href: '/advisor/household-merge', label: 'Household merge', Icon: Combine },
  { href: '/advisor/knowledge', label: 'Knowledge base', Icon: BookOpen },
  { href: '/advisor/news', label: 'News', Icon: Newspaper },
];

export function AdvisorShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white">
      <IconRail householdId="advisor" />
      <aside className="w-[240px] border-r border-zinc-200 bg-white flex flex-col">
        <div className="h-14 px-4 flex items-center border-b border-zinc-200">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/stackwealth-logo.png" alt="stackwealth" className="h-6 w-auto select-none" />
        </div>
        <nav className="p-2 flex flex-col gap-0.5 text-sm">
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2 px-2 py-1.5 rounded-md ${
                pathname === href ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-600 hover:bg-zinc-50'
              }`}
            >
              <Icon size={14} /> {label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="flex-1 min-w-0 overflow-y-auto px-10 py-8">{children}</main>
      <Toast />
    </div>
  );
}
