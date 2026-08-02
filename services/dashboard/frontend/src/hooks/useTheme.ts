import { useCallback, useEffect, useState } from 'react';

/** Supported theme values. */
type Theme = 'dark' | 'light';

/** Storage key for persisting theme preference. */
const STORAGE_KEY = 'theme';

/** Default theme when no preference is stored. */
const DEFAULT_THEME: Theme = 'dark';

/**
 * Return value of the useTheme hook.
 */
interface UseThemeResult {
  /** The current active theme. */
  theme: Theme;
  /** Toggle between dark and light themes. */
  toggleTheme: () => void;
}

/**
 * Hook for managing dark/light theme state.
 *
 * Reads the initial theme from localStorage (defaulting to dark),
 * applies the `data-theme` attribute to the document root element,
 * and persists changes back to localStorage on toggle.
 *
 * @returns The current theme and a toggle function.
 */
export function useTheme(): UseThemeResult {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : DEFAULT_THEME;
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  }, []);

  return { theme, toggleTheme };
}
