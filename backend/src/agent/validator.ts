/**
 * Numbers-from-tools validator.
 *
 * Hard rule from the design plan: any number named in an assistant message
 * must be present in a recent tool result (or be a small ordinal). The
 * validator scans the response, extracts numeric tokens, and flags ones
 * that are not in the bag of seen tool-result numbers.
 *
 * Behavior on violation: rewrite the offending token to `«unverified: <n>»`
 * so the chat surfaces the issue without dropping the message.
 */

const PERMISSIBLE_SMALL = new Set([
  '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10',
  '12', '15', '20', '25', '30', '45', '50', '60', '75', '80', '100',
]);

export function collectNumbers(value: unknown, out: Set<string> = new Set()): Set<string> {
  if (value == null) return out;
  if (typeof value === 'number' && Number.isFinite(value)) {
    out.add(String(Math.round(value)));
    return out;
  }
  if (typeof value === 'string') return out;
  if (Array.isArray(value)) {
    value.forEach((v) => collectNumbers(v, out));
    return out;
  }
  if (typeof value === 'object') {
    Object.values(value as Record<string, unknown>).forEach((v) => collectNumbers(v, out));
  }
  return out;
}

export function validateAssistantText(text: string, knownNumbers: Set<string>): string {
  const known = new Set([...knownNumbers, ...PERMISSIBLE_SMALL]);
  return text.replace(/(?<![\w.])(-?\d{1,3}(?:,\d{3})+|-?\d+(?:\.\d+)?)/g, (token) => {
    const stripped = token.replace(/,/g, '').replace(/\.0+$/, '');
    if (known.has(stripped)) return token;
    // Allow values within ±1 of a known integer to absorb rounding.
    const n = Number(stripped);
    if (Number.isFinite(n)) {
      const r = Math.round(n);
      if (known.has(String(r)) || known.has(String(r - 1)) || known.has(String(r + 1))) return token;
    }
    return `«unverified:${token}»`;
  });
}
