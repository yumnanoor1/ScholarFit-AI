/**
 * Shared text formatting for the admin pages.
 *
 * One formatter, so "varies_by_institution" reads the same way in the
 * Duplicates comparison, the Review Queue panel and the Discovery cards
 * instead of each page inventing its own `.replace(/_/g, ' ')`.
 */

/** A bare lowercase token: the shape a stored enum has. */
const ENUM_TOKEN = /^[a-z0-9]+(?:_[a-z0-9]+)*$/;

/**
 * A stored enum as a reader would write it: "full" -> "Full",
 * "varies_by_institution" -> "Varies by institution".
 *
 * Only a bare lowercase token is touched. Anything carrying a capital, a
 * space or punctuation is already prose, a name, a date or a URL, and comes
 * back exactly as it went in. A comma-separated list is humanized item by
 * item, but only when every item is a token.
 *
 * This is display only. Nothing that compares values may use it, or two
 * genuinely different values could be made to look the same.
 */
export function humanizeEnum(value) {
  if (typeof value !== 'string' || !value) return value;
  const parts = value.split(',').map((part) => part.trim());
  if (!parts.every((part) => ENUM_TOKEN.test(part))) return value;
  return parts
    .map((part) => {
      const words = part.replace(/_/g, ' ');
      return words.charAt(0).toUpperCase() + words.slice(1);
    })
    .join(', ');
}

/**
 * Whether two stored values say the same thing.
 *
 * Case and run-of-whitespace differences are not differences an
 * administrator needs to arbitrate: "Full" and "full  " are the same answer
 * written twice. Anything else counts.
 */
export function isSameStoredValue(first, second) {
  const fold = (value) => (typeof value === 'string' ? value : String(value ?? ''))
    .split(/\s+/)
    .join(' ')
    .trim()
    .toLowerCase();
  return fold(first) === fold(second);
}
