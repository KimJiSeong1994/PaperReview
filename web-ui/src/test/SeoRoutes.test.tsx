import { Suspense } from 'react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '../App';
import BlogPage from '../components/BlogPage';
import SharedView from '../components/SharedView';
import SharedCurriculumView from '../components/SharedCurriculumView';
import { AuthProvider } from '../contexts/AuthContext';
import { fetchBlogPost, fetchBlogPosts, getSharedBookmark, getSharedCurriculum } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchBlogPosts: vi.fn().mockResolvedValue({ data: { posts: [] } }),
    fetchBlogPost: vi.fn(),
    getSharedBookmark: vi.fn(),
    getSharedCurriculum: vi.fn(),
    verifyToken: vi.fn().mockResolvedValue({ role: 'user' }),
  };
});

const blogPost = {
  id: 'post-1',
  slug: 'direct-slug',
  title: 'Direct Slug Post',
  excerpt: 'Direct slug excerpt',
  content: 'Loaded from the direct slug route.',
  author: 'Jiphyeonjeon Team',
  tags: ['SEO'],
  reading_time_min: 3,
  created_at: '2026-06-14T00:00:00.000Z',
  updated_at: '2026-06-14T00:00:00.000Z',
};

const blogPostResponse = { data: blogPost } as unknown as Awaited<ReturnType<typeof fetchBlogPost>>;

function installStorageShim(): void {
  const store: Record<string, string> = {};
  const shim: Storage = {
    getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: (key) => { delete store[key]; },
    clear: () => { for (const key of Object.keys(store)) delete store[key]; },
    key: (index) => Object.keys(store)[index] ?? null,
    get length() { return Object.keys(store).length; },
  };
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, writable: true, value: shim });
  Object.defineProperty(window, 'localStorage', { configurable: true, writable: true, value: shim });
}

function renderWithAuth(path: string, ui: ReactElement) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}

describe('SEO-sensitive routes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.scrollTo = vi.fn();
    installStorageShim();
    localStorage.clear();
    document.head.innerHTML = '';
    document.title = '';
    document.documentElement.setAttribute('data-theme', 'dark');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps the existing search experience on the root route', async () => {
    renderWithAuth('/', <App />);

    expect(await screen.findByRole('heading', {
      level: 1,
      name: /Jiphyeonjeon.*집현전/,
    })).toBeInTheDocument();
    expect(screen.getByText('The AI Search Engine You Control')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(screen.queryByRole('heading', {
      name: /논문을 찾은 뒤, 근거까지 읽습니다\./,
    })).not.toBeInTheDocument();

    await waitFor(() => {
      expect(document.title).toBe('AI 논문 검색·리뷰 도구 | 집현전');
    });
    expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute(
      'content',
      expect.stringContaining('원문 근거'),
    );
    expect(document.head.querySelector('meta[property="og:locale"]')).toHaveAttribute(
      'content',
      'ko_KR',
    );
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
      'content',
      'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1',
    );

    const themeToggle = screen.getByRole('button', { name: 'Switch to light mode' });
    const mainNavigation = screen.getByRole('navigation', { name: 'Main navigation' });
    const displaySettings = screen.getByRole('group', { name: 'Display settings' });
    expect(within(mainNavigation).queryByRole('button', { name: 'Switch to light mode' })).not.toBeInTheDocument();
    expect(within(displaySettings).getByRole('button', { name: 'Switch to light mode' })).toBe(themeToggle);
    fireEvent.click(themeToggle);
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
    expect(localStorage.getItem('theme')).toBe('light');
    expect(themeToggle).toHaveAccessibleName('Switch to dark mode');
  });

  it('routes /blog/:slug directly to BlogPage and fetches the slug detail', async () => {
    vi.mocked(fetchBlogPost).mockResolvedValue(blogPostResponse);

    renderWithAuth('/blog/direct-slug', <App />);

    await waitFor(() => {
      expect(fetchBlogPost).toHaveBeenCalledWith('direct-slug');
    });
    expect(await screen.findByRole('heading', { name: 'Direct Slug Post' })).toBeInTheDocument();
    expect(screen.getByText('Loaded from the direct slug route.')).toBeInTheDocument();
  });

  it('keeps indented display math from swallowing later blog content', async () => {
    vi.mocked(fetchBlogPost).mockResolvedValue({
      data: {
        ...blogPost,
        content: String.raw`- formula:
  \[
  \mathcal{U}(s)=x
  \]
  explanation

- $\mathcal{P}:2^V\to V$

![scheduler figure](/api/blog/figures/scheduler.png)

Content after the formula.`,
      },
    } as unknown as Awaited<ReturnType<typeof fetchBlogPost>>);

    const { container } = renderWithAuth(
      '/blog/direct-slug',
      <Routes>
        <Route path="/blog/:slug" element={<BlogPage isAdmin={false} slug="direct-slug" />} />
      </Routes>,
    );

    expect(await screen.findByText('Content after the formula.')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'scheduler figure' })).toBeInTheDocument();
    expect(container.querySelector('.katex-error')).not.toBeInTheDocument();
    expect(container.querySelectorAll('.katex').length).toBeGreaterThanOrEqual(2);
  });

  it('hides urban spatial sociology from the blog sidebar only', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue({
      data: {
        posts: [{ ...blogPost, category: 'paper-review', published: true }],
      },
    } as unknown as Awaited<ReturnType<typeof fetchBlogPosts>>);

    renderWithAuth(
      '/blog',
      <Routes>
        <Route path="/blog" element={<BlogPage isAdmin={false} />} />
      </Routes>,
    );

    const sidebar = await screen.findByRole('tablist', {
      name: 'Filter posts by category',
    });
    expect(within(sidebar).getByRole('link', {
      name: /GNN 논문 리뷰 시리즈/,
    })).toBeInTheDocument();
    expect(within(sidebar).getByRole('link', {
      name: /GraphRAG 논문 리뷰 시리즈/,
    })).toBeInTheDocument();
    expect(within(sidebar).queryByRole('link', {
      name: /도시공간 사회학 논문 리뷰 시리즈/,
    })).not.toBeInTheDocument();
  });

  it('serves the public introduction route with English-first metadata', async () => {
    renderWithAuth('/introduce', <App />);

    expect(await screen.findByRole('heading', {
      name: /Find the papers.*Read the evidence/i,
    })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'About' })).toHaveAttribute('href', '/introduce/');
    expect(screen.getByText('What kind of AI paper search tool is Jiphyeonjeon?')).toBeInTheDocument();
    const languageTabs = screen.getByRole('navigation', { name: 'Introduction language' });
    expect(within(languageTabs).getByRole('link', { name: '한국어' })).toHaveAttribute('href', '/ko/introduce/');
    expect(within(languageTabs).getByRole('link', { name: '한국어' })).not.toHaveAttribute('aria-current');
    expect(within(languageTabs).getByRole('link', { name: 'English' })).toHaveAttribute('aria-current', 'page');

    await waitFor(() => {
      expect(document.title).toBe('AI Paper Search & Review | About Jiphyeonjeon');
    });
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'https://jiphyeonjeon.kr/introduce/',
    );
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
      'content',
      'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1',
    );
    expect(document.head.querySelector('meta[property="og:image"]')).toHaveAttribute(
      'content',
      'https://jiphyeonjeon.kr/og-default.jpg',
    );
    expect(document.head.querySelector('meta[property="og:locale"]')).toHaveAttribute(
      'content',
      'en_US',
    );
    expect(document.documentElement).toHaveAttribute('lang', 'en');
    expect(document.head.querySelector('link[rel="alternate"][hreflang="ko"]')).toHaveAttribute(
      'href',
      'https://jiphyeonjeon.kr/ko/introduce/',
    );
    expect(document.head.querySelectorAll('link[rel="alternate"]')).toHaveLength(3);
    const graph = JSON.parse(document.querySelector('script#seo-json-ld')?.textContent || '{}');
    expect(graph['@graph'].some((node: Record<string, unknown>) => node['@type'] === 'AboutPage')).toBe(true);
  });

  it('serves a separately indexable Korean introduction route', async () => {
    renderWithAuth('/ko/introduce', <App />);

    expect(await screen.findByRole('heading', {
      name: /논문을 찾은 뒤.*근거까지 읽습니다/,
    })).toBeInTheDocument();
    expect(screen.getByText('집현전은 어떤 AI 논문 검색 도구인가요?')).toBeInTheDocument();
    const languageTabs = screen.getByRole('navigation', { name: '소개 페이지 언어' });
    expect(within(languageTabs).getByRole('link', { name: '한국어' })).toHaveAttribute('aria-current', 'page');
    expect(within(languageTabs).getByRole('link', { name: 'English' })).toHaveAttribute('href', '/introduce/');
    expect(within(languageTabs).getByRole('link', { name: 'English' })).not.toHaveAttribute('aria-current');

    await waitFor(() => {
      expect(document.title).toBe('AI 논문 검색·리뷰 도구 | 집현전 소개');
    });
    expect(document.documentElement).toHaveAttribute('lang', 'ko');
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'https://jiphyeonjeon.kr/ko/introduce/',
    );
    expect(document.head.querySelector('meta[property="og:locale"]')).toHaveAttribute(
      'content',
      'ko_KR',
    );
    const graph = JSON.parse(document.querySelector('script#seo-json-ld')?.textContent || '{}');
    const about = graph['@graph'].find((node: Record<string, unknown>) => node['@type'] === 'AboutPage');
    expect(about.inLanguage).toBe('ko');
  });

  it('supports BlogPage slug mode without first loading the list', async () => {
    vi.mocked(fetchBlogPost).mockResolvedValue(blogPostResponse);

    renderWithAuth(
      '/blog/direct-slug',
      <Routes>
        <Route path="/blog/:slug" element={<BlogPage isAdmin={false} slug="direct-slug" />} />
      </Routes>,
    );

    await waitFor(() => expect(fetchBlogPost).toHaveBeenCalledWith('direct-slug'));
    expect(fetchBlogPosts).not.toHaveBeenCalled();
    expect(await screen.findByRole('heading', { name: 'Direct Slug Post' })).toBeInTheDocument();
  });

  it('marks 404 blog slug loads noindex,nofollow instead of indexing a soft 404', async () => {
    const notFound = Object.assign(new Error('missing'), { response: { status: 404 } });
    vi.mocked(fetchBlogPost).mockRejectedValue(notFound);

    renderWithAuth(
      '/blog/missing-slug',
      <Routes>
        <Route path="/blog/:slug" element={<BlogPage isAdmin={false} slug="missing-slug" />} />
      </Routes>,
    );

    expect(await screen.findByText('missing')).toBeInTheDocument();
    await waitFor(() => {
      expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
        'content',
        'noindex,nofollow',
      );
    });
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'https://jiphyeonjeon.kr/blog',
    );
  });

  it('does NOT noindex a blog slug when the fetch fails without a 404/410', async () => {
    // Google's Web Rendering Service blocks robots-disallowed XHRs, which
    // surfaces as a network-style failure with no HTTP status. That must not
    // override the server-rendered "index, follow" for a real post.
    vi.mocked(fetchBlogPost).mockRejectedValue(new Error('Network Error'));

    renderWithAuth(
      '/blog/real-post-slug',
      <Routes>
        <Route path="/blog/:slug" element={<BlogPage isAdmin={false} slug="real-post-slug" />} />
      </Routes>,
    );

    expect(await screen.findByText('Network Error')).toBeInTheDocument();
    await waitFor(() => {
      const robots = document.head.querySelector('meta[name="robots"]');
      expect(robots?.getAttribute('content') ?? '').not.toContain('noindex');
    });
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'https://jiphyeonjeon.kr/blog/real-post-slug',
    );
  });

  it('marks shared report token routes noindex,nofollow', async () => {
    vi.mocked(getSharedBookmark).mockResolvedValue({
      id: 'shared-1',
      title: 'Private Shared Report',
      query: 'private query',
      papers: [],
      num_papers: 1,
      report_markdown: 'Private report body',
      created_at: '2026-06-14T00:00:00.000Z',
      tags: [],
      topic: 'private topic',
      highlights: [],
    });

    renderWithAuth(
      '/share/token-123',
      <Routes>
        <Route
          path="/share/:token"
          element={
            <Suspense fallback={<div>Loading...</div>}>
              <SharedView />
            </Suspense>
          }
        />
      </Routes>,
    );

    expect(await screen.findByRole('heading', { name: 'Private Shared Report' })).toBeInTheDocument();
    await waitFor(() => {
      expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
        'content',
        'noindex,nofollow',
      );
    });
  });

  it('marks shared curriculum token routes noindex,nofollow', async () => {
    vi.mocked(getSharedCurriculum).mockResolvedValue({
      summary: {
        id: 'curriculum-1',
        name: 'Private Curriculum',
        description: 'Private curriculum body',
        difficulty: 'beginner',
        university: 'Jiphyeonjeon',
        instructor: 'Instructor',
        prerequisites: [],
        total_papers: 0,
        total_modules: 1,
      },
      course: {
        modules: [
          {
            id: 'module-1',
            title: 'Module 1',
            week: 1,
            description: 'Module description',
            topics: [],
          },
        ],
      },
    });

    renderWithAuth(
      '/share/curriculum/token-123',
      <Routes>
        <Route
          path="/share/curriculum/:token"
          element={
            <Suspense fallback={<div>Loading...</div>}>
              <SharedCurriculumView />
            </Suspense>
          }
        />
      </Routes>,
    );

    expect(await screen.findByRole('heading', { name: 'Private Curriculum' })).toBeInTheDocument();
    await waitFor(() => {
      expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
        'content',
        'noindex,nofollow',
      );
    });
  });

  it('resets private route robots metadata to indexable on the public home route', async () => {
    vi.mocked(getSharedBookmark).mockResolvedValue({
      id: 'shared-1',
      title: 'Private Shared Report',
      query: 'private query',
      papers: [],
      num_papers: 1,
      report_markdown: 'Private report body',
      created_at: '2026-06-14T00:00:00.000Z',
      tags: [],
      topic: 'private topic',
      highlights: [],
    });

    const { unmount } = render(
      <MemoryRouter initialEntries={['/share/token-123']}>
        <AuthProvider>
          <Routes>
            <Route
              path="/share/:token"
              element={
                <Suspense fallback={<div>Loading...</div>}>
                  <SharedView />
                </Suspense>
              }
            />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
        'content',
        'noindex,nofollow',
      );
    });

    unmount();

    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
        'content',
        'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1',
      );
      expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
        'href',
        'https://jiphyeonjeon.kr/',
      );
    });
  });
});
