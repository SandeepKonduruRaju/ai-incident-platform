import { useState } from 'react';
import { THEMES, applyTheme, readThemePreference, storeThemePreference, type ThemePreference } from '../theme';
import styles from './ThemeToggle.module.css';

const LABELS: Record<ThemePreference, string> = { light: 'Light', dark: 'Dark', system: 'System' };

/** Light / dark / system, as a radio group (arrow keys move between options, like any radio group). */
export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemePreference>(readThemePreference);

  function choose(next: ThemePreference) {
    setTheme(next);
    applyTheme(next);
    storeThemePreference(next);
  }

  return (
    <fieldset className={styles.toggle}>
      <legend className="visually-hidden">Theme</legend>
      {THEMES.map((option) => (
        <label key={option} className={styles.option}>
          <input type="radio" name="theme" value={option} checked={theme === option} onChange={() => choose(option)} />
          <span>{LABELS[option]}</span>
        </label>
      ))}
    </fieldset>
  );
}
