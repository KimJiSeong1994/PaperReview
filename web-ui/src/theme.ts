// Global light/dark theme control.
//
// The initial `data-theme` is set on <html> by an inline script in index.html
// (before first paint, from localStorage or the dark default). This module
// reads/updates it at runtime and persists the user's explicit choice.

import { useCallback, useState } from 'react';

export type Theme = 'light' | 'dark';

export function getTheme(): Theme {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

export function setTheme(theme: Theme): void {
  // Only flip data-theme; color-scheme is scoped to .blog-container in CSS so
  // the (still dark-only) rest of the app keeps its dark form controls.
  document.documentElement.setAttribute('data-theme', theme);
  try {
    localStorage.setItem('theme', theme);
  } catch {
    /* localStorage unavailable — the attribute still applies for this session */
  }
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === 'dark' ? 'light' : 'dark';
  setTheme(next);
  return next;
}

/** React hook for a theme toggle control. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setThemeState] = useState<Theme>(getTheme);
  const toggle = useCallback(() => {
    setThemeState(toggleTheme());
  }, []);
  return { theme, toggle };
}
