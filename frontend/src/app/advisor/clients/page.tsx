import { AdvisorShell } from '@/components/shell/AdvisorShell';
import { ClientsTable } from '@/components/advisor/ClientsTable';

export const dynamic = 'force-dynamic';

export default function ClientsPage() {
  return (
    <AdvisorShell>
      <header className="mb-6">
        <h1 className="text-2xl font-medium">Clients</h1>
        <p className="text-sm text-zinc-500">All households under your advisory.</p>
      </header>
      <ClientsTable />
    </AdvisorShell>
  );
}
