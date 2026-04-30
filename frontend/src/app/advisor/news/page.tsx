import { AdvisorShell } from '@/components/shell/AdvisorShell';
import { NewsBoard } from '@/components/advisor/NewsBoard';

export const dynamic = 'force-dynamic';

export default function NewsPage() {
  return (
    <AdvisorShell>
      <header className="mb-6">
        <h1 className="text-2xl font-medium">News</h1>
        <p className="text-sm text-zinc-500">
          Today’s items and the clients they materially affect, scored against holdings and asset class.
        </p>
      </header>
      <NewsBoard />
    </AdvisorShell>
  );
}
