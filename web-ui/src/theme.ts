// Global light/dark theme control.
//
// The initial `data-theme` is set on <html> by an inline script in index.html
// (before first paint): an explicit saved choice, else the OS
// prefers-color-scheme, else dark. This module reads/updates it at runtime
// and persists the user's explicit choice — writing localStorage is what
// pins a reader to their pick and stops the OS preference applying again.

import { useCallback, useEffect, useState } from 'react';

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

/**
 * Reactive read-only theme hook. Unlike `useTheme`, this subscribes to
 * `<html data-theme>` mutations, so a component re-renders when *any* toggle
 * flips the theme (the toggle button lives elsewhere in the tree). Needed by
 * canvas/SVG renderers (Plotly, Sigma) that must recompute colors on toggle.
 */
export function useThemeObserver(): Theme {
  const [theme, setThemeState] = useState<Theme>(getTheme);
  useEffect(() => {
    const observer = new MutationObserver(() => setThemeState(getTheme()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
    // Sync in case the attribute changed between initial state and subscription.
    setThemeState(getTheme());
    return () => observer.disconnect();
  }, []);
  return theme;
}
