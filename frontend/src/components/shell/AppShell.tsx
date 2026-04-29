'use client';

import { IconRail } from './IconRail';

/**
 * 3-column shell — icon rail · chat panel · canvas — matches the reference at ~5/25/70.
 */
export function AppShell({
  householdId,
  children,
}: {
  householdId: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-white">
      <IconRail householdId={householdId} />
      {children}
    </div>
  );
}
