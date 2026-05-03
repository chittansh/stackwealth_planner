import { ReportView } from '@/components/report/ReportView';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Stackwealth — Plan summary',
};

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      {/* Cormorant Garamond — used for serif headings + the cover. */}
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,500&display=swap"
        rel="stylesheet"
      />
      <ReportView householdId={id} />
    </>
  );
}
