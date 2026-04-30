import { ReportView } from '@/components/report/ReportView';

export const dynamic = 'force-dynamic';

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReportView householdId={id} />;
}
