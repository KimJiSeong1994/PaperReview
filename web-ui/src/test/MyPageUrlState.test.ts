import { describe, it, expect } from 'vitest';
import { paramsWithBookmark } from '../components/MyPage';

// MyPage has one view (bookmarks) and no tabs: old ?tab=papers and ?tab=memory
// links simply open it, which MyPage.viewer.test covers.
describe('paramsWithBookmark', () => {
  it('replaces rather than appends, so the id cannot accumulate', () => {
    const next = paramsWithBookmark(new URLSearchParams('bookmark=old'), 'bm_new');
    expect(next.getAll('bookmark')).toEqual(['bm_new']);
  });

  it('leaves every other parameter alone', () => {
    const next = paramsWithBookmark(new URLSearchParams('tab=memory&q=graph'), 'bm_1');
    expect(next.get('bookmark')).toBe('bm_1');
    expect(next.get('tab')).toBe('memory');
    expect(next.get('q')).toBe('graph');
  });
});
