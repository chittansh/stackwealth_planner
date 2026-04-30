import { AdvisorShell } from '@/components/shell/AdvisorShell';
import { HouseholdMerge } from '@/components/advisor/HouseholdMerge';

export const dynamic = 'force-dynamic';

export default function HouseholdMergePage() {
  return (
    <AdvisorShell>
      <header className="mb-6">
        <h1 className="text-2xl font-medium">Household merge</h1>
        <p className="text-sm text-zinc-500">Combine eligible clients into one household plan.</p>
      </header>
      <HouseholdMerge />
    </AdvisorShell>
  );
}
