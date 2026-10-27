import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { THEME_STORAGE_KEY, readThemePreference } from '../theme';
import { ThemeToggle } from './ThemeToggle';

describe('ThemeToggle', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it('defaults to system, pins light or dark on <html>, and remembers the choice', async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(screen.getByRole('radio', { name: 'System' })).toBeChecked();
    expect(document.documentElement.dataset.theme).toBeUndefined();

    await user.click(screen.getByRole('radio', { name: 'Dark' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');

    await user.click(screen.getByRole('radio', { name: 'Light' }));
    expect(document.documentElement.dataset.theme).toBe('light');

    await user.click(screen.getByRole('radio', { name: 'System' }));
    expect(document.documentElement.dataset.theme).toBeUndefined(); // back to prefers-color-scheme
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('starts from the saved choice, and ignores a garbage value', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    render(<ThemeToggle />);
    expect(screen.getByRole('radio', { name: 'Dark' })).toBeChecked();

    window.localStorage.setItem(THEME_STORAGE_KEY, 'neon');
    expect(readThemePreference()).toBe('system');
  });

  it('still switches when storage is unavailable (private mode, blocked site data)', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(screen.getByRole('radio', { name: 'System' })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: 'Dark' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(screen.getByRole('radio', { name: 'Dark' })).toBeChecked();
  });
});
