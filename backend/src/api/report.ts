import { Hono } from 'hono';
import { renderPlanPdf } from '../skills/report/pdf.js';

export const reportRoute = new Hono();

reportRoute.get('/:id/pdf', async (c) => {
  const id = c.req.param('id');
  const r = await renderPlanPdf(id);
  if (r.ok) {
    return new Response(new Uint8Array(r.bytes), {
      status: 200,
      headers: {
        'content-type': 'application/pdf',
        'content-disposition': `attachment; filename="stackwealth-plan-${id}.pdf"`,
      },
    });
  }
  return new Response(r.html, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } });
});
