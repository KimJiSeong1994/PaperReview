import { describe, it, expect, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useThemeObserver } from '../theme';

describe('useThemeObserver', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('data-theme');
  });

  it('returns the current theme and reacts to data-theme mutations', async () => {
    document.documentElement.setAttribute('data-theme', 'dark');
    const { result } = renderHook(() => useThemeObserver());
    expect(result.current).toBe('dark');

    // MutationObserver delivers on a microtask; the async act flush drains it.
    await act(async () => {
      document.documentElement.setAttribute('data-theme', 'light');
    });
    expect(result.current).toBe('light');
  });
});
