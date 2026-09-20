import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useBookmarks } from '../hooks/useBookmarks';
import { getBookmarks } from '../api/client';
import type { Bookmark } from '../components/mypage/types';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, getBookmarks: vi.fn() };
});

const bookmark: Bookmark = {
  id: 'bm_1', title: 'Graph RAG', session_id: 's1', query: 'graph rag',
  num_papers: 3, created_at: '2026-09-01T00:00:00Z', tags: [], topic: 'RAG',
};
type ListResponse = Awaited<ReturnType<typeof getBookmarks>>;
const list = (bookmarks: Bookmark[]) => ({ bookmarks } as unknown as ListResponse);

beforeEach(() => vi.clearAllMocks());

describe('useBookmarks loading', () => {
  it('leaves the first request to the page, and a refresh keeps the list on screen', async () => {
    vi.mocked(getBookmarks).mockResolvedValue(list([bookmark]));
    const { result } = renderHook(() => useBookmarks());
    // MyPage's tab effect is the one caller on mount; a second request here doubled it.
    expect(getBookmarks).not.toHaveBeenCalled();

    await act(async () => { await result.current.loadBookmarks(); });
    expect(result.current.bookmarks).toHaveLength(1);
    expect(result.current.loadingBookmarks).toBe(false);

    let resolve!: (value: ListResponse) => void;
    vi.mocked(getBookmarks).mockReturnValueOnce(new Promise<ListResponse>((r) => { resolve = r; }));
    act(() => { void result.current.loadBookmarks(); });
    // The list is still there while the refresh is in flight — no "Loading..." swap.
    expect(result.current.loadingBookmarks).toBe(false);
    expect(result.current.bookmarks).toHaveLength(1);

    await act(async () => { resolve(list([bookmark])); });
    expect(getBookmarks).toHaveBeenCalledTimes(2);
  });

  it('lets one request run at a time, so back-to-back callers cannot race', async () => {
    let resolve!: (value: ListResponse) => void;
    vi.mocked(getBookmarks).mockReturnValueOnce(new Promise<ListResponse>((r) => { resolve = r; }));
    const { result } = renderHook(() => useBookmarks());
    act(() => { void result.current.loadBookmarks(); void result.current.loadBookmarks(); });
    expect(getBookmarks).toHaveBeenCalledTimes(1);
    await act(async () => { resolve(list([bookmark])); });
    expect(result.current.bookmarks).toHaveLength(1);

    vi.mocked(getBookmarks).mockResolvedValueOnce(list([]));
    await act(async () => { await result.current.loadBookmarks(); });
    expect(getBookmarks).toHaveBeenCalledTimes(2);
  });

  it('still shows the loading state when there is nothing on screen yet', async () => {
    let resolve!: (value: ListResponse) => void;
    vi.mocked(getBookmarks).mockReturnValueOnce(new Promise<ListResponse>((r) => { resolve = r; }));
    const { result } = renderHook(() => useBookmarks());
    act(() => { void result.current.loadBookmarks(); });
    expect(result.current.loadingBookmarks).toBe(true);
    await act(async () => { resolve(list([])); });
    expect(result.current.loadingBookmarks).toBe(false);
  });
});
