"""
Report PDF — port of skills/report/pdf.ts.

Stub: returns a printable HTML fallback with guidance. The TS version uses
Puppeteer; the equivalent here would be Playwright/WeasyPrint and is left
for a follow-up.
"""
from __future__ import annotations


async def render_plan_pdf(household_id: str) -> dict:
    html = f"""<!doctype html><html><body style="font-family: sans-serif; padding:2rem;">
<h1>Stackwealth Plan — {household_id}</h1>
<p>Server-side PDF rendering isn't enabled on this build. Use the browser's
<strong>Print → Save as PDF</strong> from the plan page, or install
<code>playwright</code> and wire <code>render_plan_pdf</code>.</p>
</body></html>"""
    return {"ok": False, "html": html}
