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

const url = process.env.DATABASE_URL;

const client = url ? postgres(url, { prepare: false }) : null;
export const db = client ? drizzle(client, { schema }) : null;

const memory = new Map<string, PlanState>();

function ensureFixture(household_id: string): PlanState {
  if (memory.has(household_id)) return memory.get(household_id)!;
  const fixture = emptyPlanState(household_id);
  fixture.personal_details.full_name = 'Demo Household';
  memory.set(household_id, fixture);
  return fixture;
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
