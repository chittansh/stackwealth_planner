import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Stackwealth Planner',
  description: 'AI-native financial planner for Indian households and advisors.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-white text-zinc-900 antialiased">{children}</body>
    </html>
  );
}
