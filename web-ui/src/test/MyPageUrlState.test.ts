import { describe, it, expect } from 'vitest';
import { tabFromParams, paramsWithTab, paramsWithBookmark } from '../components/MyPage';

describe('tabFromParams', () => {
  it('reads the tab that is not the default', () => {
    expect(tabFromParams('papers')).toBe('papers');
  });

  it('falls back to bookmarks for absent or unrecognised values', () => {
    expect(tabFromParams(null)).toBe('bookmarks');
    expect(tabFromParams('')).toBe('bookmarks');
    expect(tabFromParams('bookmarks')).toBe('bookmarks');
    expect(tabFromParams('nonsense')).toBe('bookmarks');
    // The old tab value is handled by MyPage as a redirect, not as a tab.
    expect(tabFromParams('curriculum')).toBe('bookmarks');
  });
});

describe('paramsWithTab', () => {
  it('records a non-default tab', () => {
    expect(paramsWithTab(new URLSearchParams(), 'papers').get('tab')).toBe('papers');
  });

  it('drops the key for the default rather than writing tab=bookmarks', () => {
    const next = paramsWithTab(new URLSearchParams('tab=papers'), 'bookmarks');
    expect(next.has('tab')).toBe(false);
  });

  it('leaves every other parameter alone', () => {
    const next = paramsWithTab(new URLSearchParams('bookmark=bm_1&q=graph'), 'papers');
    expect(next.get('bookmark')).toBe('bm_1');
    expect(next.get('q')).toBe('graph');
    expect(next.get('tab')).toBe('papers');
  });
});

describe('paramsWithBookmark', () => {
  it('replaces rather than appends, so the id cannot accumulate', () => {
    const next = paramsWithBookmark(new URLSearchParams('bookmark=old'), 'bm_new');
    expect(next.getAll('bookmark')).toEqual(['bm_new']);
  });

  it('keeps the tab that is already recorded', () => {
    const next = paramsWithBookmark(new URLSearchParams('tab=papers'), 'bm_1');
    expect(next.get('tab')).toBe('papers');
  });
});

describe('round trip', () => {
  it('a written URL reads back as the same tab', () => {
    for (const tab of ['bookmarks', 'papers'] as const) {
      const written = paramsWithTab(new URLSearchParams(), tab);
      expect(tabFromParams(written.get('tab'))).toBe(tab);
    }
  });
});
