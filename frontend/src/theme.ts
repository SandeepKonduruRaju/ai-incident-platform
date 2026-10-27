// Theme preference: 'system' follows prefers-color-scheme (tokens.css); 'light'/'dark' pin it via <html data-theme>.
// Stored in localStorage (a display preference, not a secret); every access is guarded because storage can be
// unavailable (private windows, blocked site data) and the page must still render.
export const THEMES = ['light', 'dark', 'system'] as const;
export type ThemePreference = (typeof THEMES)[number];

export const THEME_STORAGE_KEY = 'incident-platform.theme';

export function readThemePreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return (THEMES as readonly string[]).includes(value ?? '') ? (value as ThemePreference) : 'system';
  } catch {
    return 'system';
  }
}

export function storeThemePreference(theme: ThemePreference): void {
  try {
    if (theme === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Not saved: the choice still applies until the page is reloaded.
  }
}

export function applyTheme(theme: ThemePreference, root: HTMLElement = document.documentElement): void {
  if (theme === 'system') delete root.dataset.theme;
  else root.dataset.theme = theme;
}
