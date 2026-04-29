import { AppShell } from '@/components/shell/AppShell';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { Headline } from '@/components/canvas/Headline';
import { NetWorthChart } from '@/components/canvas/NetWorthChart';
import { PlanBlocks } from '@/components/canvas/PlanBlocks';
import { TopBar } from '@/components/shell/TopBar';

export default async function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  return (
    <AppShell householdId={id}>
      <ChatPanel householdId={id} />
      <main className="flex-1 min-w-0 flex flex-col">
        <TopBar householdId={id} />
        <div className="flex-1 overflow-y-auto px-10 py-8">
          <Headline householdId={id} />
          <div className="mt-6">
            <NetWorthChart householdId={id} />
          </div>
          <div className="mt-10">
            <PlanBlocks householdId={id} />
          </div>
        </div>
      </main>
    </AppShell>
  );
}
