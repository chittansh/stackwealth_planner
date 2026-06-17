import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Stackwealth Planner',
  description: 'AI-native financial planner for Indian households and advisors.',
};

// Inline pre-paint theme bootstrap. Runs before React hydrates so the
// first paint matches the user's saved choice — no flash of light theme
// when the saved preference is dark. Falls back to "light" when nothing
// is stored (we don't auto-follow OS — see the comment in globals.css).
const THEME_BOOTSTRAP = `
try {
  var t = localStorage.getItem('sw.theme');
  if (t === 'dark' || t === 'light') {
    document.documentElement.setAttribute('data-theme', t);
  }
} catch (e) {}
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="antialiased">{children}</body>
    </html>
  );
}
