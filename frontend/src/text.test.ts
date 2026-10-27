import { describe, expect, it } from 'vitest';
import { safeNextPath, truncateAtWord } from './text';

describe('truncateAtWord', () => {
  it('returns short text unchanged', () => {
    expect(truncateAtWord('restored the index', 200)).toEqual({ text: 'restored the index', truncated: false });
    expect(truncateAtWord('x'.repeat(10), 10)).toEqual({ text: 'x'.repeat(10), truncated: false });
  });

  it('cuts at the last word boundary and adds an ellipsis, never mid-word', () => {
    const text = 'Rebuilt and restored the index; writes resumed after the failover completed';
    const result = truncateAtWord(text, 33); // a hard cut would end in "restored the index; w"
    expect(result).toEqual({ text: 'Rebuilt and restored the index…', truncated: true });
    expect(result.text).not.toMatch(/ w…$/);
  });

  it('keeps a word that ends exactly at the limit', () => {
    expect(truncateAtWord('alpha beta gamma', 10)).toEqual({ text: 'alpha beta…', truncated: true });
  });

  it('cuts a single overlong word hard, still with an ellipsis', () => {
    expect(truncateAtWord('a'.repeat(30), 10)).toEqual({ text: `${'a'.repeat(10)}…`, truncated: true });
  });
});

describe('safeNextPath (no open redirect)', () => {
  it('accepts same-origin relative paths, with query and hash', () => {
    expect(safeNextPath('/incidents/0b9f4d6e-7a1c-4c2e-9d55-2f1e8a3b6c01')).toBe('/incidents/0b9f4d6e-7a1c-4c2e-9d55-2f1e8a3b6c01');
    expect(safeNextPath('/incidents?page=2#top')).toBe('/incidents?page=2#top');
  });

  it.each([
    '//evil.com',
    '//evil.com/incidents',
    '/\\evil.com',
    'https://evil.com',
    'http://localhost:3001/incidents', // absolute, even to ourselves: only relative paths are accepted
    'javascript:alert(1)',
    'evil.com',
    '',
    null,
    undefined,
  ])('rejects %s and falls back to /incidents', (value) => {
    expect(safeNextPath(value)).toBe('/incidents');
  });

  it('never returns to the login page itself', () => {
    expect(safeNextPath('/login?next=/incidents')).toBe('/incidents');
  });
});
