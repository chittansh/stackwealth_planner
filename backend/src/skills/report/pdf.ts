/**
 * Server-side PDF render via Puppeteer.
 *
 * Hits the Next.js print-styled route at /plan/:id/report and prints to PDF.
 * In Vercel-style serverless, swap `puppeteer` for `puppeteer-core` +
 * `@sparticuz/chromium` (still call `launch` the same way).
 *
 * Dependency policy: puppeteer is intentionally an OPTIONAL runtime dep.
 * If it's not installed, the route falls back to a printable HTML response.
 */

const FRONTEND = process.env.FRONTEND_ORIGIN ?? 'http://localhost:3000';

export async function renderPlanPdf(household_id: string): Promise<{ ok: true; bytes: Buffer } | { ok: false; html: string }> {
  type LaunchedBrowser = {
    newPage: () => Promise<{
      goto: (url: string, opts: { waitUntil: string; timeout: number }) => Promise<unknown>;
      pdf: (opts: { format: string; printBackground: boolean; margin: Record<string, string> }) => Promise<Buffer | Uint8Array>;
    }>;
    close: () => Promise<void>;
  };
  type PuppeteerLike = {
    launch: (opts: { headless: boolean | 'new'; args: string[] }) => Promise<LaunchedBrowser>;
  };

  let puppeteer: PuppeteerLike | null = null;
  try {
    puppeteer = (await import('puppeteer')) as unknown as PuppeteerLike;
  } catch {
    puppeteer = null;
  }

  if (!puppeteer) {
    const html = `<!doctype html><meta charset="utf-8"/>
<title>Report — ${household_id}</title>
<body style="font-family: ui-sans-serif; padding: 32px; color: #18181b;">
  <p>Server-side PDF rendering requires <code>puppeteer</code>. Install it on the backend and retry.</p>
  <p>In the meantime, open <a href="${FRONTEND}/plan/${household_id}/report">the print-styled report</a>
     in a browser and use <em>Print → Save as PDF</em>.</p>
</body>`;
    return { ok: false, html };
  }

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  try {
    const page = await browser.newPage();
    await page.goto(`${FRONTEND}/plan/${household_id}/report`, { waitUntil: 'networkidle0', timeout: 30_000 });
    const pdf = await page.pdf({
      format: 'A4',
      printBackground: true,
      margin: { top: '12mm', right: '12mm', bottom: '12mm', left: '12mm' },
    });
    return { ok: true, bytes: Buffer.from(pdf as Uint8Array) };
  } finally {
    await browser.close().catch(() => undefined);
  }
}
