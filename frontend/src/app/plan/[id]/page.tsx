import { AppShell } from '@/components/shell/AppShell';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { TopBar } from '@/components/shell/TopBar';
import { CanvasRouter } from '@/components/canvas/CanvasRouter';

export default async function PlanPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ view?: string; horizon?: string }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const view = (sp.view ?? 'net-worth') as
    | 'net-worth'
    | 'cash-flow'
    | 'allocation'
    | 'goals'
    | 'insurance'
    | 'tax'
    | 'debt'
    | 'retirement'
    | 'risk';
  const horizon = Number(sp.horizon ?? 45);

  return (
    <AppShell householdId={id}>
      <ChatPanel householdId={id} />
      <main className="flex-1 min-w-0 flex flex-col">
        <TopBar householdId={id} view={view} horizon={horizon} />
        <div className="flex-1 overflow-y-auto px-10 py-8">
          <CanvasRouter householdId={id} view={view} horizon={horizon} />
        </div>
      </main>
    </AppShell>
  );
}
