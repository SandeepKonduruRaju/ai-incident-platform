import { describe, expect, it } from 'vitest';
import { citationNumber, splitSentences } from './components/CitedText';
import { formatDateTime, formatFullDateTime, formatRelative } from './format';

describe('date formatting (en-IE)', () => {
  it('formats a short date and time like "26 Oct, 22:24"', () => {
    expect(formatDateTime('2026-10-26T22:24:00Z', 'UTC')).toBe('26 Oct, 22:24');
    expect(formatDateTime('2026-03-05T07:05:00Z', 'UTC')).toBe('5 Mar, 07:05');
  });

  it('uses the given time zone (the browser zone when none is given)', () => {
    expect(formatDateTime('2026-10-26T22:24:00Z', 'Asia/Kolkata')).toBe('27 Oct, 03:54');
  });

  it('gives the full, unambiguous date for tooltips', () => {
    expect(formatFullDateTime('2026-10-26T22:24:00Z', 'UTC')).toBe('Monday 26 October 2026 at 22:24');
  });
});

describe('relative time', () => {
  const now = new Date('2026-10-27T12:00:00Z');
  it.each([
    ['2026-10-27T11:59:40Z', 'now'],
    ['2026-10-27T11:55:00Z', '5 min ago'],
    ['2026-10-27T10:00:00Z', '2 hr ago'],
    ['2026-10-26T11:00:00Z', '1 day ago'],
    ['2026-10-20T12:00:00Z', '1 wk ago'],
    ['2026-10-24T12:00:00Z', '3 days ago'],
    ['2026-10-06T12:00:00Z', '3 wk ago'],
    ['2026-07-27T12:00:00Z', '3 mo ago'],
    ['2024-10-27T12:00:00Z', '2 yr ago'],
  ])('%s -> %s', (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });
});

describe('citation text helpers', () => {
  it('numbers marks from their labels', () => {
    expect(citationNumber('C12')).toBe('12');
    expect(citationNumber('X1')).toBe('X1');
  });

  it('splits sentences and keeps a marker placed after the full stop with its sentence', () => {
    expect(splitSentences('Pool exhausted [C1]. Deploy at 12:00. [C2] Traffic doubled [C3][C4].')).toEqual([
      'Pool exhausted [C1].',
      'Deploy at 12:00. [C2]',
      'Traffic doubled [C3][C4].',
    ]);
    expect(splitSentences('No sentence end [C1]')).toEqual(['No sentence end [C1]']);
  });
});
