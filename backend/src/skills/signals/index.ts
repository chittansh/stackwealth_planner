/**
 * India market signal block.
 *
 * Live fetchers are stubbed — they would hit NSE/RBI/AMFI/NSDL on Day 6.
 * For now we read a fixture snapshot file (`signals.fixture.json`) so the
 * demo is reproducible and never depends on a network fetch.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

export type SignalBlocks = {
  valuation: { score: number; reason: string };
  trend: { score: number; reason: string };
  breadth: { score: number; reason: string };
  flows: { score: number; reason: string };
  macro: { score: number; reason: string };
  external: { score: number; reason: string };
};

export type SignalSnapshot = {
  as_of: string;
  blocks: SignalBlocks;
  source_versions: Record<string, string>;
};

let cached: SignalSnapshot | null = null;

export function getSignals(): SignalSnapshot {
  if (cached) return cached;
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const path = resolve(here, '../../seed/signals.fixture.json');
    cached = JSON.parse(readFileSync(path, 'utf8')) as SignalSnapshot;
    return cached;
  } catch {
    cached = {
      as_of: new Date().toISOString().slice(0, 10),
      blocks: {
        valuation: { score: 0, reason: 'Neutral (no snapshot)' },
        trend: { score: 0, reason: 'Neutral' },
        breadth: { score: 0, reason: 'Neutral' },
        flows: { score: 0, reason: 'Neutral' },
        macro: { score: 0, reason: 'Neutral' },
        external: { score: 0, reason: 'Neutral' },
      },
      source_versions: {},
    };
    return cached;
  }
}

export function regimeFromBlocks(b: SignalBlocks): { score: number; label: string } {
  const s = b.valuation.score + b.trend.score + b.breadth.score + b.flows.score + b.macro.score + b.external.score;
  const label =
    s >= 4 ? 'Risk-On' :
    s >= 1 ? 'Mild Risk-On' :
    s >= -1 ? 'Neutral' :
    s >= -4 ? 'Mild Defensive' : 'Defensive';
  return { score: s, label };
}
