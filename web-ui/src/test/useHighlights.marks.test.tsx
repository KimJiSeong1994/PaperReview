import { describe, it, expect, vi } from 'vitest';
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { createRef } from 'react';
import { useHighlights } from '../hooks/useHighlights';
import type { HighlightItem } from '../api/client';

const highlight = (over: Partial<HighlightItem>): HighlightItem => ({
  id: 'h1', text: 'key phrase', color: '#a5b4fc', memo: '', created_at: '2026-09-01T00:00:00Z', ...over,
});

describe('useHighlights marks', () => {
  it('makes only a highlight with something behind it a keyboard control, and Enter opens its popover', () => {
    const { result } = renderHook(() => useHighlights(null, { id: 'bm_1' }, vi.fn(), createRef<HTMLDivElement>()));
    act(() => {
      result.current.initFromDetail('', [
        highlight({ id: 'h1', text: 'key phrase', memo: 'why it matters' }),
        highlight({ id: 'h2', text: 'plain run' }),
      ]);
    });
    render(<p>{result.current.applyUserHighlights('a key phrase and a plain run')}</p>);

    const control = screen.getByRole('button', { name: 'key phrase' });
    expect(screen.getByText('plain run')).not.toHaveAttribute('role');
    expect(screen.getByText('plain run')).not.toHaveAttribute('tabindex');

    fireEvent.keyDown(control, { key: 'Enter' });
    expect(result.current.highlightPopover?.hl.id).toBe('h1');
    fireEvent.keyDown(control, { key: ' ' });
    expect(result.current.highlightPopover).toBeNull();
  });
});
