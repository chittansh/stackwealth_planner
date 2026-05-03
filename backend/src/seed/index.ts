/**
 * No-op on boot. Households, news, and KB documents are all created on
 * demand by the user — first GET on /api/plan/:id auto-creates an empty
 * plan, KB uploads create org docs, news items are added by whatever
 * fetcher you wire up.
 *
 * Kept as an export so backend/src/index.ts doesn't need to change to drop
 * the call.
 */
export async function runSeed(): Promise<void> {
  /* nothing to do */
}
