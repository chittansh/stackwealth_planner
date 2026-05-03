/**
 * DB client — Postgres via Drizzle when DATABASE_URL is set.
 * Falls back to an in-memory map when not set, so the dev server boots
 * without a Neon project on Day 1.
 */
import postgres from 'postgres';
import { drizzle } from 'drizzle-orm/postgres-js';
import { eq } from 'drizzle-orm';
import * as schema from './schema.js';
import { emptyPlanState, type PlanState } from '../types/plan-state.js';

const rawUrl = process.env.DATABASE_URL?.trim();
// Treat the .env.example placeholder (or any obviously-fake URL) as "unset" so
// the backend falls back to the in-memory store instead of trying to dial a
// host that doesn't exist.
const isPlaceholder =
  !rawUrl ||
  rawUrl.includes('user:pass@host') ||
  rawUrl.includes('your-neon-host') ||
  rawUrl === 'postgres://';
const url = isPlaceholder ? null : rawUrl;

if (rawUrl && isPlaceholder) {
  console.warn('[db] DATABASE_URL looks like a placeholder — using in-memory store instead.');
}

const client = url ? postgres(url, { prepare: false }) : null;
export const db = client ? drizzle(client, { schema }) : null;

const memory = new Map<string, PlanState>();

function ensureFixture(household_id: string): PlanState {
  if (memory.has(household_id)) return memory.get(household_id)!;
  // Brand-new household — start fully empty. The agent / UI will fill in
  // personal_details on the first user turn.
  const blank = emptyPlanState(household_id);
  memory.set(household_id, blank);
  return blank;
}

export async function getPlan(household_id: string): Promise<PlanState | null> {
  if (db) {
    const row = await db.select().from(schema.plan_states).where(eq(schema.plan_states.household_id, household_id)).limit(1);
    if (row[0]) return row[0].state as PlanState;
    return null;
  }
  return ensureFixture(household_id);
}

export async function savePlan(plan: PlanState): Promise<void> {
  if (db) {
    await db
      .insert(schema.plan_states)
      .values({ household_id: plan.household_id, state: plan, last_updated_at: new Date() })
      .onConflictDoUpdate({
        target: schema.plan_states.household_id,
        set: { state: plan, last_updated_at: new Date() },
      });
    return;
  }
  memory.set(plan.household_id, plan);
}

export async function listAllHouseholds(): Promise<string[]> {
  if (db) {
    const rows = await db.select({ id: schema.plan_states.household_id }).from(schema.plan_states);
    return rows.map((r) => r.id);
  }
  return [...memory.keys()];
}

/**
 * Seed an in-memory plan state (used by the seed script and tests).
 * No-op on the DB path — call savePlan for that.
 */
export function seedMemory(plan: PlanState): void {
  memory.set(plan.household_id, plan);
}
