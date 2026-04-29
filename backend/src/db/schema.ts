/**
 * Drizzle schema. Postgres + pgvector.
 *
 * Most canonical sections are stored as JSONB to avoid mid-week migrations.
 * The reading shape on the wire is `PlanState` from /shared/types.
 */
import { pgTable, text, timestamp, jsonb, integer, doublePrecision, index } from 'drizzle-orm/pg-core';
import { sql } from 'drizzle-orm';

export const orgs = pgTable('orgs', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  created_at: timestamp('created_at').defaultNow().notNull(),
});

export const users = pgTable('users', {
  id: text('id').primaryKey(),
  org_id: text('org_id').references(() => orgs.id),
  email: text('email').notNull().unique(),
  name: text('name'),
  role: text('role').default('advisor').notNull(),
  created_at: timestamp('created_at').defaultNow().notNull(),
});

export const households = pgTable('households', {
  id: text('id').primaryKey(),
  org_id: text('org_id').references(() => orgs.id),
  name: text('name').notNull(),
  created_at: timestamp('created_at').defaultNow().notNull(),
});

export const plan_states = pgTable('plan_states', {
  household_id: text('household_id').primaryKey().references(() => households.id),
  state: jsonb('state').notNull(),                // PlanState
  last_updated_at: timestamp('last_updated_at').defaultNow().notNull(),
});

export const chat_messages = pgTable('chat_messages', {
  id: text('id').primaryKey(),
  household_id: text('household_id').references(() => households.id).notNull(),
  role: text('role').notNull(),                   // user | assistant | system | tool
  content: jsonb('content').notNull(),
  created_at: timestamp('created_at').defaultNow().notNull(),
}, (t) => ({
  byHousehold: index('chat_household_idx').on(t.household_id, t.created_at),
}));

export const evidence_log = pgTable('evidence_log', {
  id: text('id').primaryKey(),
  household_id: text('household_id').references(() => households.id).notNull(),
  field: text('field').notNull(),
  value: jsonb('value'),
  source_file: text('source_file'),
  source_type: text('source_type').notNull(),
  parser_tier: text('parser_tier').notNull(),
  confidence: doublePrecision('confidence').notNull(),
  evidence_quote: text('evidence_quote'),
  created_at: timestamp('created_at').defaultNow().notNull(),
});

export const kb_documents = pgTable('kb_documents', {
  id: text('id').primaryKey(),
  org_id: text('org_id').references(() => orgs.id).notNull(),
  filename: text('filename').notNull(),
  uploaded_at: timestamp('uploaded_at').defaultNow().notNull(),
});

export const kb_chunks = pgTable('kb_chunks', {
  id: text('id').primaryKey(),
  document_id: text('document_id').references(() => kb_documents.id).notNull(),
  org_id: text('org_id').references(() => orgs.id).notNull(),
  heading: text('heading'),
  text: text('text').notNull(),
  // pgvector — declared via raw SQL; populate with extension migration on Day 1.
  embedding: text('embedding'),  // store as JSON-serialized vector for v0; switch to vector type once pgvector is present
  ord: integer('ord').notNull(),
});

export const news_items = pgTable('news_items', {
  id: text('id').primaryKey(),
  title: text('title').notNull(),
  summary: text('summary'),
  sectors: jsonb('sectors'),       // string[]
  isins: jsonb('isins'),           // string[]
  published_at: timestamp('published_at').notNull(),
});

export const signal_snapshots = pgTable('signal_snapshots', {
  as_of: text('as_of').primaryKey(),       // YYYY-MM-DD
  blocks: jsonb('blocks').notNull(),       // 6 signal block scores
  source_versions: jsonb('source_versions'),
});

export const householdMergeAudit = pgTable('household_merge_audit', {
  id: text('id').primaryKey(),
  parent_household_id: text('parent_household_id').notNull(),
  child_client_ids: jsonb('child_client_ids').notNull(),
  performed_by: text('performed_by').notNull(),
  performed_at: timestamp('performed_at').defaultNow().notNull(),
});

// pgvector extension bootstrap — run once via drizzle-kit push or migration.
export const enablePgvector = sql`CREATE EXTENSION IF NOT EXISTS vector;`;
