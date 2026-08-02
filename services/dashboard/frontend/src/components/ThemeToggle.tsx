import { useTheme } from '../hooks/useTheme';

/**
 * Toggle button for switching between dark and light themes.
 *
 * Displays a sun icon in dark mode and a moon icon in light mode.
 * Theme preference is persisted to localStorage via the useTheme hook.
 */
export function ThemeToggle(): React.JSX.Element {
  const { theme, toggleTheme } = useTheme();

  return (
    <button className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
      {theme === 'dark' ? '\u2600\uFE0F' : '\uD83C\uDF19'}
    </button>
  );
}
