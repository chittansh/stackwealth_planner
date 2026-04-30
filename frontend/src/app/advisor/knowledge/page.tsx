import { AdvisorShell } from '@/components/shell/AdvisorShell';
import { KnowledgeUpload } from '@/components/advisor/KnowledgeUpload';

export const dynamic = 'force-dynamic';

export default function KnowledgePage() {
  return (
    <AdvisorShell>
      <header className="mb-6">
        <h1 className="text-2xl font-medium">Knowledge base</h1>
        <p className="text-sm text-zinc-500">
          Upload firm research, MF policies, allocation memos. The agent cites these inline in chat.
        </p>
      </header>
      <KnowledgeUpload />
    </AdvisorShell>
  );
}
