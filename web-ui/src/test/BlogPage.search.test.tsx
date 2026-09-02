import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import BlogPage from '../components/BlogPage';
import { fetchBlogPosts } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchBlogPosts: vi.fn(),
    fetchBlogPost: vi.fn(),
  };
});

function post(id: string, title: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    slug: id,
    title,
    excerpt: `${title} excerpt`,
    content: '',
    author: 'Jiphyeonjeon Team',
    tags: ['Search'],
    category: 'engineering',
    reading_time_min: 3,
    created_at: '2026-06-14T00:00:00.000Z',
    updated_at: '2026-06-14T00:00:00.000Z',
    ...extra,
  };
}

const ALL_POSTS = [post('a', 'Ranking rewrite'), post('b', 'Crawler health')];

/** 12 matches — pages of 5, 5, 2, so both a full and a short last page exist. */
const MANY_RESULTS = Array.from({ length: 12 }, (_, i) => post(`p${i}`, `Match ${i}`));

type PostsResponse = Awaited<ReturnType<typeof fetchBlogPosts>>;
const respond = (posts: unknown[]) => ({ data: { posts } }) as unknown as PostsResponse;

/** Calls carrying the 5th (`q`) argument — i.e. searches, not the initial load-all. */
function searchCalls() {
  return vi.mocked(fetchBlogPosts).mock.calls.filter((call) => Boolean(call[4]));
}

/** Mirrors the live URL into the DOM so tests can assert on ?q=. */
function LocationProbe() {
  const { pathname, search } = useLocation();
  return <span data-testid="location">{`${pathname}${search}`}</span>;
}

function renderBlog(entry = '/blog') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BlogPage isAdmin={false} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

/** The overlay is the only place search lives — everything below goes through it. */
function openSearch() {
  fireEvent.click(screen.getByLabelText('블로그 글 검색'));
}

async function type(value: string) {
  fireEvent.change(screen.getByLabelText('검색어'), { target: { value } });
}

/** Result rows inside the overlay, so the list underneath can't satisfy a match. */
function resultTitles() {
  return Array.from(document.querySelectorAll('.blog-search-result-title')).map((n) => n.textContent);
}

/** The overlay's own pager — scoped, so the list's pager underneath can't stand in. */
function searchPager() {
  return within(screen.getByRole('dialog')).queryByLabelText('페이지');
}

function pageButton(label: string) {
  return within(screen.getByRole('dialog')).getByLabelText(label);
}

/** Runs a query that matches MANY_RESULTS and waits for the first page to land. */
async function searchMany(q: string) {
  vi.mocked(fetchBlogPosts).mockResolvedValue(respond(MANY_RESULTS));
  await type(q);
  await waitFor(() => expect(resultTitles()).toHaveLength(5));
}

describe('BlogPage search overlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(ALL_POSTS));
  });

  it('opens from the header icon and focuses the input', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    openSearch();

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText('검색어'));
    // Must stay a child of .blog-container: every --wov-*/--indigo* token is
    // scoped to it (and re-declared under :root[data-theme="light"]), so a
    // portal to <body> would render the overlay unstyled in both themes.
    expect(document.querySelector('.blog-container > .blog-search-overlay')).toBeTruthy();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText('블로그 글 검색'));
  });

  it('suggests the 3 most recent posts while the query is empty', async () => {
    const many = ['a', 'b', 'c', 'd'].map((id, i) => post(id, `Post ${i}`));
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(many));
    renderBlog();
    // Load barrier only. findAll, not find: with 4 posts the list also renders
    // the hero carousel, so the newest title is on screen twice by design.
    await screen.findAllByText('Post 0');

    openSearch();

    // The 최근 아티클 heading is asserted separately; this is about the rows.
    expect(resultTitles()).toEqual(['Post 0', 'Post 1', 'Post 2']);
    // The suggestions reuse the already-loaded list rather than refetching.
    expect(searchCalls()).toHaveLength(0);
  });

  it('debounces typing into a single query carrying q', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('r');
    await type('ra');
    await type('rank');

    await waitFor(() => expect(searchCalls()).toHaveLength(1));
    expect(searchCalls()[0][4]).toBe('rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
  });

  it('shows the body snippet instead of the stored excerpt', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', { snippet: '…we reworked rank fusion…' })]),
    );
    await type('rank');

    const dialog = within(await screen.findByRole('dialog'));
    const snippet = await dialog.findByText(/we reworked/);
    expect(snippet).toHaveTextContent('…we reworked rank fusion…');
    expect(dialog.queryByText(/Ranking rewrite excerpt/)).not.toBeInTheDocument();
  });

  it('restores the unsearched state when the overlay is closed', async () => {
    renderBlog();
    await screen.findByText('Crawler health');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));

    fireEvent.click(screen.getByLabelText('검색 닫기'));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // Reopening starts clean rather than resurrecting the last query.
    openSearch();
    expect(screen.getByLabelText('검색어')).toHaveValue('');
    expect(resultTitles()).toEqual(ALL_POSTS.map((p) => p.title));
  });

  it('runs the query from ?q= on mount so a shared link reloads searched', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    renderBlog('/blog?q=rank');

    await waitFor(() => expect(searchCalls()).toHaveLength(1));
    expect(searchCalls()[0][4]).toBe('rank');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('검색어')).toHaveValue('rank');
  });

  it('survives a click on the takeover background without dropping ?q=', async () => {
    // The overlay is a full-screen opaque takeover, so *every* stray click lands
    // on it. While it closed on backdrop mousedown, one click after opening a
    // shared /blog?q=… link closed the search and replaced the URL with /blog —
    // which read as "the link never opened the overlay at all".
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    renderBlog('/blog?q=rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));

    const overlay = document.querySelector('.blog-search-overlay') as HTMLElement;
    fireEvent.mouseDown(overlay);
    fireEvent.click(overlay);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('검색어')).toHaveValue('rank');
    expect(screen.getByTestId('location')).toHaveTextContent('/blog?q=rank');
  });

  it('still shows search results when the initial load-all failed', async () => {
    // The overlay must not inherit the list's empty/error state — a failed
    // load-all used to hide valid search results behind "게시물이 없습니다".
    vi.mocked(fetchBlogPosts).mockRejectedValueOnce(new Error('boom'));
    renderBlog();
    await screen.findByText('게시물이 없습니다');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('rank');

    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
  });

  it('reports a failed search as a failure, not as "no results"', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    // e.g. a 422 from an over-long query, or any network error.
    vi.mocked(fetchBlogPosts).mockRejectedValue(new Error('boom'));
    await type('rank');

    expect(await screen.findByText('검색을 완료하지 못했습니다')).toBeInTheDocument();
    expect(screen.queryByText('검색 결과가 없어요')).not.toBeInTheDocument();
  });

  it('clears the search failure once the overlay is closed', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockRejectedValue(new Error('boom'));
    await type('rank');
    await screen.findByText('검색을 완료하지 못했습니다');

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(ALL_POSTS));
    fireEvent.click(screen.getByLabelText('검색 닫기'));
    openSearch();

    expect(screen.queryByText('검색을 완료하지 못했습니다')).not.toBeInTheDocument();
    // Reopening lands back on the suggestion list.
    expect(resultTitles()).toEqual(ALL_POSTS.map((p) => p.title));
  });

  it('does not blame the search when only the load-all failed', async () => {
    // Shared error state used to invert the fix: a *successful* empty search
    // reported itself as failed because load-all had errored earlier.
    vi.mocked(fetchBlogPosts).mockImplementation(((...args: unknown[]) =>
      args[4] ? Promise.resolve(respond([])) : Promise.reject(new Error('boom'))) as never);
    renderBlog('/blog?q=zzz');

    expect(await screen.findByText('검색 결과가 없어요')).toBeInTheDocument();
    expect(screen.queryByText('검색을 완료하지 못했습니다')).not.toBeInTheDocument();
  });

  it('does not flash "no results" while the request is still in flight', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    // The flash lasts a single render, so watch every mutation rather than
    // sampling: the render that publishes the debounced query lands before the
    // effect that flags `searching`, and used to paint the empty state with no
    // response yet in hand.
    const flashes: string[] = [];
    const observer = new MutationObserver(() => {
      const text = document.body.textContent ?? '';
      if (text.includes('검색 결과가 없어요')) flashes.push('empty');
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    vi.mocked(fetchBlogPosts).mockReturnValue(new Promise(() => {}) as never);
    await type('zzz');
    await waitFor(() => expect(searchCalls()).toHaveLength(1));
    observer.disconnect();

    expect(flashes).toEqual([]);
  });

  it('gives a result row the same figure the list already fetched, lazily', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', { thumbnail_url: '/api/blog/figures/fig-a.png' })]),
    );
    await type('rank');

    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
    // Scoped to the row: alt="" keeps the figure out of the a11y tree, and the
    // overlay's brand logo is the only <img> with a role.
    const img = document.querySelector('.blog-search-result-thumb img') as HTMLImageElement;
    // w=456 and not w=228: the list rows under the overlay request the very
    // same URL, so a post visible in the list costs no extra bytes here.
    expect(img).toHaveAttribute('src', '/api/blog/figures/fig-a.png?w=456');
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(img).toHaveAttribute('decoding', 'async');
    // Explicit box, so the row does not reflow when the figure lands.
    expect(img).toHaveAttribute('width', '164');
    expect(img).toHaveAttribute('height', '92');
  });

  it('renders a thumbnail-less result as a row with no image at all', async () => {
    // Never a broken image and never a shorter row: min-height holds the
    // geometry and the text column simply takes the width.
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', { thumbnail_url: null })]),
    );
    await type('rank');

    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
    const row = document.querySelector('.blog-search-result') as HTMLElement;
    expect(row.querySelector('img')).toBeNull();
    expect(row.querySelector('.blog-search-result-thumb')).toBeNull();
  });

  it('carries title and snippet only — no category chip, no author', async () => {
    // The search row is deliberately lighter than the list row it covers.
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', {
        snippet: '…we reworked rank fusion…',
        author: 'Hong Gildong',
        category: 'paper-review',
      })]),
    );
    await type('rank');

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText(/we reworked/)).toBeInTheDocument();
    expect(within(dialog).queryByText('Hong Gildong')).not.toBeInTheDocument();
    expect(within(dialog).queryByText('Paper Review')).not.toBeInTheDocument();
    expect(dialog.querySelector('.blog-row-cat')).toBeNull();
    expect(dialog.querySelector('.blog-row-author')).toBeNull();
  });

  it('opens on Cmd+K and on Ctrl+K from anywhere on the page', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');

    fireEvent.keyDown(document.body, { key: 'k', metaKey: true });
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('leaves the shortcut alone while the user is typing in another input', async () => {
    // Ctrl+K is a live keystroke inside a text field (kill-to-end-of-line on
    // macOS, and the admin editor has fields of its own). Stealing it there
    // would eat the user's edit and open a search they did not ask for.
    renderBlog();
    await screen.findByText('Ranking rewrite');

    const elsewhere = document.createElement('input');
    elsewhere.type = 'text';
    document.body.appendChild(elsewhere);
    elsewhere.focus();

    fireEvent.keyDown(elsewhere, { key: 'k', metaKey: true });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    elsewhere.remove();
  });

  it('preventDefaults the shortcut so the browser keeps its own Ctrl+K', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');

    // fireEvent returns false once a listener has called preventDefault.
    const notCancelled = fireEvent.keyDown(document.body, {
      key: 'k',
      ctrlKey: true,
      cancelable: true,
    });

    expect(notCancelled).toBe(false);
  });

  it('labels the list 최근 아티클 while empty and 검색 결과 / 총 N개 once searched', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.getByText('최근 아티클')).toBeInTheDocument();
    expect(dialog.queryByText('검색 결과')).not.toBeInTheDocument();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));

    expect(dialog.getByText('검색 결과')).toBeInTheDocument();
    expect(dialog.getByText('총 1개')).toBeInTheDocument();
    expect(dialog.queryByText('최근 아티클')).not.toBeInTheDocument();
  });

  it('keeps the visible count out of the a11y tree so it is not said twice', async () => {
    // Both the label and the sr-only live region carry the count. The live
    // region is the spoken one; the label must stay decorative or a reader
    // hears the same number from two places.
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));

    expect(document.querySelector('.blog-search-section')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('검색 결과 1개');
  });

  it('advertises the shortcut on the trigger itself', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');

    const trigger = screen.getByLabelText('블로그 글 검색');
    expect(trigger).toHaveTextContent('검색');
    expect(trigger.querySelector('kbd')).toHaveTextContent('Ctrl K');
  });

  it('renders the no-results state when nothing matches', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([]));
    await type('zzz');

    expect(await screen.findByText('검색 결과가 없어요')).toBeInTheDocument();
  });
  // ── Result pagination ───────────────────────────────────────────────

  it('shows 5 results a page and walks the rest through the pager', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    expect(resultTitles()).toEqual(['Match 0', 'Match 1', 'Match 2', 'Match 3', 'Match 4']);
    expect(searchPager()).toBeTruthy();

    fireEvent.click(pageButton('2페이지'));

    expect(resultTitles()).toEqual(['Match 5', 'Match 6', 'Match 7', 'Match 8', 'Match 9']);
    expect(pageButton('2페이지')).toHaveAttribute('aria-current', 'page');
  });

  it('scrolls the box that actually scrolls when the page changes', async () => {
    // The overlay carries overflow-y, not the results list inside it. Resetting
    // the inner element's scrollTop moved nothing, so paging left the reader
    // partway down the previous page — invisible to a test that only asserts
    // some scrollTo ran, hence the assertion on which node received it.
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    const overlay = document.querySelector('.blog-search-overlay') as HTMLElement;
    const list = document.querySelector('.blog-search-results') as HTMLElement;
    overlay.scrollTop = 240;
    list.scrollTop = 240;

    fireEvent.click(pageButton('2페이지'));

    // The effect, not the call: asserting "some scrollTo ran" passed happily
    // while the wrong element was being reset.
    expect(overlay.scrollTop).toBe(0);
    expect(list.scrollTop).toBe(240);
  });

  it('keeps the count on the whole result set, not the page', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    // A reader looking at 5 rows still needs to know the search found 12.
    expect(within(screen.getByRole('dialog')).getByText('총 12개')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('검색 결과 12개');
  });

  it('leaves the empty-query suggestion list unpaged', async () => {
    // 12 posts loaded, so the list underneath does page — the overlay's three
    // suggestions are not a result set and must not grow a pager of their own.
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(MANY_RESULTS));
    renderBlog();
    await screen.findAllByText('Match 0');
    openSearch();

    expect(resultTitles()).toEqual(['Match 0', 'Match 1', 'Match 2']);
    expect(searchPager()).toBeNull();
  });

  it('returns to page 1 when the query changes', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    fireEvent.click(pageButton('3페이지'));
    expect(resultTitles()).toEqual(['Match 10', 'Match 11']);

    // 7 results: page 3 would *clamp* to page 2 (Match 5, 6). Landing on
    // Match 0 is what proves the reset, not the clamp, did the work.
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(MANY_RESULTS.slice(0, 7)));
    await type('other');

    await waitFor(() =>
      expect(resultTitles()).toEqual(['Match 0', 'Match 1', 'Match 2', 'Match 3', 'Match 4']),
    );
  });

  it('disables prev on the first page and next on the last', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    expect(pageButton('이전 페이지')).toBeDisabled();
    expect(pageButton('다음 페이지')).not.toBeDisabled();

    fireEvent.click(pageButton('다음 페이지'));
    fireEvent.click(pageButton('다음 페이지'));

    expect(resultTitles()).toEqual(['Match 10', 'Match 11']);
    expect(pageButton('다음 페이지')).toBeDisabled();
    expect(pageButton('이전 페이지')).not.toBeDisabled();
  });
  // ── Arrow-key navigation ────────────────────────────────────────────

  /** The row the arrow keys have selected, read the way a screen reader does. */
  function activeRow() {
    const id = screen.getByLabelText('검색어').getAttribute('aria-activedescendant');
    return id ? document.getElementById(id)?.textContent : null;
  }

  function arrow(key: 'ArrowDown' | 'ArrowUp' | 'Enter') {
    fireEvent.keyDown(screen.getByLabelText('검색어'), { key });
  }

  it('selects the first row on ArrowDown and points aria-activedescendant at it', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    // Nothing is selected until an arrow key asks for it.
    expect(screen.getByLabelText('검색어')).not.toHaveAttribute('aria-activedescendant');

    arrow('ArrowDown');

    const rows = document.querySelectorAll('.blog-search-result');
    expect(rows[0]).toHaveAttribute('aria-selected', 'true');
    expect(rows[0]).toHaveClass('active');
    expect(activeRow()).toContain('Match 0');
    // Focus never leaves the input — moving it onto the row would steal the caret.
    expect(document.activeElement).toBe(screen.getByLabelText('검색어'));

    arrow('ArrowDown');
    expect(activeRow()).toContain('Match 1');
    expect(rows[0]).toHaveAttribute('aria-selected', 'false');
  });

  it('stops at the last row of the page instead of wrapping or paging', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    // 12 results, 5 on this page: six ArrowDowns must not reach Match 5.
    for (let i = 0; i < 6; i += 1) arrow('ArrowDown');

    expect(activeRow()).toContain('Match 4');
    expect(resultTitles()).toEqual(['Match 0', 'Match 1', 'Match 2', 'Match 3', 'Match 4']);
  });

  it('stops at the first row on ArrowUp instead of wrapping to the last', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    arrow('ArrowDown');
    arrow('ArrowDown');
    expect(activeRow()).toContain('Match 1');

    arrow('ArrowUp');
    arrow('ArrowUp');
    arrow('ArrowUp');

    expect(activeRow()).toContain('Match 0');
  });

  it('opens the active row on Enter, the same way a click does', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    arrow('ArrowDown');
    arrow('ArrowDown');
    arrow('Enter');

    // Same effect the click path has: overlay gone, URL on the post.
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/blog/p1'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does nothing on Enter while no row is active', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    const before = screen.getByTestId('location').textContent;
    arrow('Enter');

    // Guessing the first result would send a reader somewhere they never chose.
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByTestId('location').textContent).toBe(before);
    expect(screen.getByTestId('location')).not.toHaveTextContent('/blog/');
  });

  it('drops the selection when the query changes under it', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    arrow('ArrowDown');
    arrow('ArrowDown');
    expect(activeRow()).toContain('Match 1');

    // The replacement set is deliberately long enough that row 1 still exists:
    // against a shorter one the render guard would hide a stale index anyway,
    // and the test would pass without any reset at all.
    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('z', 'Other hit'), post('y', 'Second hit'), post('x', 'Third hit')]),
    );
    await type('other');
    await waitFor(() => expect(resultTitles()).toEqual(['Other hit', 'Second hit', 'Third hit']));

    // An index left pointing at whatever row 1 now happens to be must not be live.
    expect(screen.getByLabelText('검색어')).not.toHaveAttribute('aria-activedescendant');
    expect(document.querySelector('.blog-search-result.active')).toBeNull();
  });

  it('drops the selection when the page changes under it', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    arrow('ArrowDown');
    expect(activeRow()).toContain('Match 0');

    fireEvent.click(pageButton('2페이지'));

    expect(screen.getByLabelText('검색어')).not.toHaveAttribute('aria-activedescendant');
    expect(document.querySelector('.blog-search-result.active')).toBeNull();
  });

  it('keeps typing working while a row is active', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();
    await searchMany('match');

    arrow('ArrowDown');
    expect(activeRow()).toContain('Match 0');

    // The input owns focus throughout, so a keystroke still lands in the field.
    await type('match rank');

    expect(screen.getByLabelText('검색어')).toHaveValue('match rank');
  });

  it('navigates the suggestion list too, and closes on Enter there', async () => {
    renderBlog();
    await screen.findByText('Crawler health');
    openSearch();

    expect(resultTitles()).toEqual(ALL_POSTS.map((p) => p.title));
    arrow('ArrowDown');
    expect(activeRow()).toContain('Ranking rewrite');

    arrow('Enter');

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/blog/a'));
  });
});
