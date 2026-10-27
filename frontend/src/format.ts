// Dates in the en-IE style ("26 Oct, 22:24"), in the viewer's time zone unless one is given (tests pass 'UTC').
// Relative times ("2 hr ago") use Intl.RelativeTimeFormat; the full date goes in a tooltip next to them.
const LOCALE = 'en-IE';

export function formatDateTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone }).format(
    new Date(iso),
  );
}

/** "Monday 26 October 2026 at 22:24": the unambiguous form, for tooltips. */
export function formatFullDateTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: 'full', timeStyle: 'short', timeZone }).format(new Date(iso));
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
];

/** "now", "5 min ago", "2 hr ago", "1 day ago", "3 wk ago": the largest whole unit (always numeric: no "last wk"). */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) {
      return new Intl.RelativeTimeFormat(LOCALE, { numeric: 'always', style: 'narrow' }).format(Math.trunc(seconds / size), unit);
    }
  }
  return new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' }).format(0, 'second'); // "now"
}
