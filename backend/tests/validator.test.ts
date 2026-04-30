import { describe, it, expect } from 'vitest';
import { collectNumbers, validateAssistantText } from '../src/agent/validator.js';

describe('numbers-from-tools validator', () => {
  it('collects numeric leaves from a tool result', () => {
    const seen = collectNumbers({
      headline: 24_890_000,
      pillars: { liquidity: 67, debt: 80 },
      list: [{ value: 12_500 }, { value: 4 }],
    });
    expect(seen.has('24890000')).toBe(true);
    expect(seen.has('67')).toBe(true);
    expect(seen.has('12500')).toBe(true);
  });

  it('passes a number that exists in the tool bag', () => {
    const seen = new Set(['24890000']);
    const txt = 'Projected total: ₹24,890,000.';
    expect(validateAssistantText(txt, seen)).toBe(txt);
  });

  it('flags numbers that were not produced by a tool', () => {
    const seen = new Set(['24890000']);
    const txt = 'Projected total: ₹50,000,000.';
    expect(validateAssistantText(txt, seen)).toContain('«unverified:50,000,000»');
  });

  it('allows small ordinals + percent ranges without a tool source', () => {
    const seen = new Set<string>();
    const txt = 'Up to 5 years; about 30 paths.';
    const out = validateAssistantText(txt, seen);
    expect(out).not.toContain('«unverified');
  });
});
