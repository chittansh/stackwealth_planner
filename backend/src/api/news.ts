import { Hono } from 'hono';
import { randomUUID } from 'node:crypto';
import { listNews, affectedClientsForItem, seedNews, type NewsItem } from '../skills/news/index.js';

export const newsRoute = new Hono();

newsRoute.get('/', async (c) => {
  const items = listNews();
  const out = await Promise.all(
    items.map(async (it) => ({
      ...it,
      affected: await affectedClientsForItem(it),
    })),
  );
  return c.json({ items: out });
});

/**
 * Append (not replace) news items to the in-memory store.
 * Body: { items: NewsItem[] } — id + published_at are filled in if absent.
 */
newsRoute.post('/', async (c) => {
  const body = await c.req.json<{ items: Partial<NewsItem>[] }>().catch(() => ({ items: [] }));
  const incoming = (body.items ?? []).map<NewsItem>((it) => ({
    id: it.id ?? randomUUID(),
    title: it.title ?? '(untitled)',
    summary: it.summary ?? '',
    sectors: it.sectors ?? [],
    isins: it.isins ?? [],
    asset_class: (it.asset_class as NewsItem['asset_class']) ?? 'macro',
    published_at: it.published_at ?? new Date().toISOString(),
  }));
  seedNews([...listNews(), ...incoming]);
  return c.json({ ok: true, added: incoming.length, total: listNews().length });
});
