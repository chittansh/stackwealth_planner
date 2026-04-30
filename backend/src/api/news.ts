import { Hono } from 'hono';
import { listNews, affectedClientsForItem } from '../skills/news/index.js';

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
