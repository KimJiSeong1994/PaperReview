import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import BlogPage from '../components/BlogPage';
import { chooseActiveId } from '../components/BlogTableOfContents';
import { fetchBlogPosts, fetchBlogPost } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchBlogPosts: vi.fn(),
    fetchBlogPost: vi.fn(),
  };
});

/** jsdom ships neither of these; the detail view needs both to mount. */
function stubViewport(wide: boolean) {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: wide,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

class NoopIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}

const CONTENT = [
  '# DeepWalk 심층 분석',
  '',
  '## Executive Summary',
  '',
  '요약 문단.',
  '',
  '## 목차',
  '',
  '1. 배경',
  '2. 방법',
  '',
  '## 배경',
  '',
  '배경 문단.',
  '',
  '## 방법',
  '',
  '방법 문단.',
  '',
  '## References',
  '',
  '- ref',
].join('\n');

const NO_TOC_CONTENT = ['## 배경', '', '배경 문단.'].join('\n');

/**
 * The same post skeleton under the corpus's other labels: of 71 published
 * posts, 12 open with 핵심 요약 where 50 open with Executive Summary, 3 close
 * with 참고문헌, and 2 spell the index Table of Contents.
 */
const KOREAN_BOILERPLATE_CONTENT = [
  '## 핵심 요약',
  '',
  '요약 문단.',
  '',
  '## Table of Contents',
  '',
  '1. 배경',
  '',
  '## 배경',
  '',
  '배경 문단.',
  '',
  '## 참고문헌',
  '',
  '- ref',
].join('\n');

const SERIES_SLUG = 'deepwalk-online-learning-social-representations-review-2026';

function post(slug: string, content: string, extra: Record<string, unknown> = {}) {
  return {
    id: slug,
    slug,
    title: 'DeepWalk Review',
    excerpt: '랜덤워크 임베딩 리뷰.',
    content,
    author: 'Jiphyeonjeon Team',
    tags: ['GNN', 'Embedding'],
    category: 'paper-review',
    reading_time_min: 12,
    created_at: '2026-06-14T00:00:00.000Z',
    updated_at: '2026-06-14T00:00:00.000Z',
    ...extra,
  };
}

type PostResponse = Awaited<ReturnType<typeof fetchBlogPost>>;
type PostsResponse = Awaited<ReturnType<typeof fetchBlogPosts>>;

async function renderDetail(fixture: ReturnType<typeof post>) {
  vi.mocked(fetchBlogPost).mockResolvedValue({ data: fixture } as unknown as PostResponse);
  render(
    <MemoryRouter initialEntries={[`/blog/${fixture.slug}`]}>
      <BlogPage isAdmin={false} slug={fixture.slug} />
    </MemoryRouter>,
  );
  await screen.findByText('DeepWalk Review');
  return fixture;
}

/** Indices of the detail column's direct children, for order assertions. */
function childIndexOf(selector: string) {
  const column = document.querySelector('.blog-detail')!;
  return Array.from(column.children).findIndex((node) => node.matches(selector));
}

describe('chooseActiveId', () => {
  it('returns null when every heading is still below the line', () => {
    expect(chooseActiveId([{ id: 'a', top: 300 }, { id: 'b', top: 900 }], 80)).toBeNull();
  });

  it('returns the only heading that has crossed the line', () => {
    expect(chooseActiveId([{ id: 'a', top: 20 }, { id: 'b', top: 500 }], 80)).toBe('a');
  });

  it('returns the heading closest to the line when several have crossed', () => {
    const positions = [{ id: 'a', top: -900 }, { id: 'b', top: -120 }, { id: 'c', top: 400 }];
    expect(chooseActiveId(positions, 80)).toBe('b');
  });

  it('treats a heading exactly on the line as crossed', () => {
    expect(chooseActiveId([{ id: 'a', top: 80 }], 80)).toBe('a');
  });

  it('reports nothing for an empty document, so the caller keeps its value', () => {
    expect(chooseActiveId([], 80)).toBeNull();
  });
});

describe('BlogPage detail layout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubViewport(true);
    vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver);
    vi.mocked(fetchBlogPosts).mockResolvedValue({ data: { posts: [] } } as unknown as PostsResponse);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('lists the navigable h2s and skips the structural ones', async () => {
    await renderDetail(post('deepwalk', CONTENT));

    const toc = await screen.findByRole('navigation', { name: '목차' });
    const links = Array.from(toc.querySelectorAll('a')).map((a) => a.textContent);
    expect(links).toEqual(['배경', '방법']);
    expect(links).not.toContain('Executive Summary');
    expect(links).not.toContain('References');
  });

  it('links each entry to the id rehype-slug put on the heading', async () => {
    await renderDetail(post('deepwalk', CONTENT));

    const toc = await screen.findByRole('navigation', { name: '목차' });
    const href = toc.querySelector('a')!.getAttribute('href')!;
    expect(href.startsWith('#')).toBe(true);
    expect(document.querySelector(`.blog-detail-content ${href}`)).not.toBeNull();
  });

  it('tags the body 목차 heading and its list for suppression', async () => {
    await renderDetail(post('deepwalk', CONTENT));

    await waitFor(() => {
      expect(document.querySelector('.blog-detail-content h2.body-toc-heading')).not.toBeNull();
    });
    const heading = document.querySelector('.body-toc-heading')!;
    expect(heading.textContent).toBe('목차');
    expect(heading.nextElementSibling!.classList.contains('body-toc-list')).toBe(true);
  });

  it('leaves a post without a 목차 section untouched', async () => {
    await renderDetail(post('no-toc', NO_TOC_CONTENT));

    await waitFor(() => {
      expect(screen.getByText('배경 문단.')).toBeInTheDocument();
    });
    expect(document.querySelector('.body-toc-heading')).toBeNull();
    expect(document.querySelector('.body-toc-list')).toBeNull();
  });

  it('puts the meta row above the title and the tags below the dek', async () => {
    await renderDetail(post('deepwalk', CONTENT));

    expect(childIndexOf('.blog-detail-meta')).toBeLessThan(childIndexOf('.blog-detail-title'));
    expect(childIndexOf('.blog-detail-dek')).toBeLessThan(childIndexOf('.blog-detail-tags'));
    expect(childIndexOf('.blog-detail-title')).toBeLessThan(childIndexOf('.blog-detail-dek'));
    expect(screen.getByText('DeepWalk 심층 분석')).toBeInTheDocument();
    expect(screen.getByText('GNN')).toBeInTheDocument();
  });

  it('keeps the series nav and the post title intact', async () => {
    await renderDetail(post(SERIES_SLUG, CONTENT));

    const series = await screen.findByRole('navigation', { name: 'Series' });
    expect(series.textContent).toContain('GNN 논문 리뷰 시리즈');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('DeepWalk Review');
  });

  it('skips the structural h2s under their Korean and English labels alike', async () => {
    await renderDetail(post('korean', KOREAN_BOILERPLATE_CONTENT));

    const toc = await screen.findByRole('navigation', { name: '목차' });
    // 핵심 요약 and 참고문헌 are the same sections as Executive Summary and
    // References; listing them on some posts and not others is the bug.
    expect(Array.from(toc.querySelectorAll('a')).map((a) => a.textContent)).toEqual(['배경']);
  });

  it('suppresses the body index when it is headed Table of Contents', async () => {
    await renderDetail(post('korean', KOREAN_BOILERPLATE_CONTENT));

    await waitFor(() => {
      expect(document.querySelector('.body-toc-heading')).not.toBeNull();
    });
    const heading = document.querySelector('.body-toc-heading')!;
    expect(heading.textContent).toBe('Table of Contents');
    expect(heading.nextElementSibling!.classList.contains('body-toc-list')).toBe(true);
  });

  it('renders no sidebar index below the wide-viewport breakpoint', async () => {
    stubViewport(false);
    await renderDetail(post('deepwalk', CONTENT));

    expect(screen.queryByRole('navigation', { name: '목차' })).toBeNull();
    // The body's own 목차 is still tagged — CSS keeps it visible on narrow screens.
    await waitFor(() => {
      expect(document.querySelector('.body-toc-heading')).not.toBeNull();
    });
  });
});
