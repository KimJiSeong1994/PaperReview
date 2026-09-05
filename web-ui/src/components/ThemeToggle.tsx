import { useTheme } from '../theme';

interface ThemeToggleProps {
  /** English label, for the separately indexed English /introduce/ page only.
   *  Defaults to Korean: every other route this sits on is Korean, and the
   *  label reads next to the nav labels, which follow the same rule. */
  english?: boolean;
}

/** Header button that flips between light and dark themes. */
export default function ThemeToggle({ english = false }: ThemeToggleProps) {
  const { theme, toggle } = useTheme();
  const isDark = theme === 'dark';
  const label = english
    ? (isDark ? 'Switch to light mode' : 'Switch to dark mode')
    : (isDark ? '라이트 모드로 전환' : '다크 모드로 전환');
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={label}
      title={label}
    >
      {isDark ? (
        // Sun — tap to go light
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="17" height="17" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        // Moon — tap to go dark
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="17" height="17" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}
