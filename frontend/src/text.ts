/**
 * Shortens text for a preview: cuts at the last word boundary at or before `max` characters and adds "…".
 * Text that fits is returned unchanged. A single word longer than `max` is cut hard (still with "…").
 */
export function truncateAtWord(text: string, max: number): { text: string; truncated: boolean } {
  const clean = text.trim();
  if (clean.length <= max) return { text: clean, truncated: false };
  const slice = clean.slice(0, max + 1); // +1: a space right after the limit is still a boundary
  const lastSpace = slice.search(/\s\S*$/);
  const cut = lastSpace > 0 ? slice.slice(0, lastSpace) : clean.slice(0, max);
  // Do not end on punctuation that reads oddly before an ellipsis ("index; …" -> "index…").
  return { text: `${cut.replace(/[\s,;:.-]+$/, '')}…`, truncated: true };
}

/** Same-origin, relative path to return to after sign-in; anything else (absolute, protocol-relative, ...) -> fallback. */
export function safeNextPath(value: string | null | undefined, fallback = '/incidents'): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return fallback;
  try {
    const base = 'http://same-origin.invalid';
    const url = new URL(value, base);
    if (url.origin !== base) return fallback;
    const path = `${url.pathname}${url.search}${url.hash}`;
    return path.startsWith('/login') ? fallback : path; // never loop back to the login page
  } catch {
    return fallback;
  }
}
