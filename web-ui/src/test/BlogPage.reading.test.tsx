import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import BlogPage from '../components/BlogPage';
import { fetchBlogPost, fetchBlogPosts, updateBlogPost } from '../api/client';

vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  fetchBlogPost: vi.fn(), fetchBlogPosts: vi.fn(), updateBlogPost: vi.fn(),
}));

const PAPER = '**Paper:** Example Author (2024). "Example paper". https://arxiv.org/abs/2404.19737v1 · arXiv:2404.19737v1';
const EASY = `${PAPER}\n\n## 쉬운 설명\n\nEASY_ONLY`;
const DEEP = `${PAPER}\n\n## 상세 방법\n\nDEEP_ONLY\n\n## 수식 분석\n\nDetailed evidence.`;
const POST = {
  id: 'paper-id', slug: 'example-paper', title: 'Example paper', excerpt: '논문의 핵심 요약.',
  content: EASY, deep_content: DEEP, deep_reading_time_min: 29,
  reading_time_min: 5, author: 'Jiphyeonjeon Team', tags: ['paper-review'],
  category: 'paper-review', created_at: '2026-09-20T10:00:00Z', updated_at: null,
};

function RoutePage({ admin }: { admin: boolean }) {
  const { slug } = useParams();
  return <BlogPage slug={slug} isAdmin={admin} />;
}

function LocationAndBack() {
  const location = useLocation();
  const navigate = useNavigate();
  return <>
    <output data-testid="location">{location.pathname}{location.search}</output>
    <button onClick={() => navigate(-1)}>Browser back</button>
  </>;
}

function mount(url = '/blog/example-paper', admin = false) {
  return render(<MemoryRouter initialEntries={['/previous', url]}>
    <LocationAndBack />
    <Routes>
      <Route path="/blog/:slug" element={<RoutePage admin={admin} />} />
      <Route path="/previous" element={<p>PREVIOUS_PAGE</p>} />
      <Route path="/blog" element={<BlogPage isAdmin={admin} />} />
    </Routes>
  </MemoryRouter>);
}

function mockPost(extra: Record<string, unknown> = {}) {
  vi.mocked(fetchBlogPost).mockResolvedValue({ data: { ...POST, ...extra } } as never);
}

describe('blog reading levels', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('scrollTo', vi.fn());
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
    mockPost();
    vi.mocked(fetchBlogPosts).mockResolvedValue({ data: { posts: [] } } as never);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it('shows only the easy body by default with a detailed link beside PDF', async () => {
    mount();
    await screen.findByText('EASY_ONLY');
    expect(screen.queryByText('DEEP_ONLY')).not.toBeInTheDocument();
    const meta = document.querySelector('.blog-detail-meta')!;
    expect(within(meta as HTMLElement).getByRole('link', { name: /상세 읽기/ }))
      .toHaveAttribute('href', '/blog/example-paper?view=deep');
    expect(within(meta as HTMLElement).getByRole('link', { name: /PDF 보기/ })).toBeInTheDocument();
    expect(screen.getByText('5 min read')).toBeInTheDocument();
  });

  it('switches body, reading time, TOC and structured data and preserves Back history', async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText('EASY_ONLY');
    await user.click(screen.getByRole('link', { name: /상세 읽기/ }));
    await screen.findByText('DEEP_ONLY');
    expect(screen.queryByText('EASY_ONLY')).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('?view=deep');
    expect(screen.getByText('29 min read')).toBeInTheDocument();
    const toc = await screen.findByRole('navigation', { name: '목차' });
    await waitFor(() => expect(within(toc).getByRole('link', { name: '상세 방법' })).toBeInTheDocument());
    expect(within(toc).queryByRole('link', { name: '쉬운 설명' })).not.toBeInTheDocument();
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute('href', 'https://jiphyeonjeon.kr/blog/example-paper');
    expect(document.querySelector('script[type="application/ld+json"]')?.textContent).toContain('DEEP_ONLY');
    await user.click(screen.getByRole('button', { name: 'Browser back' }));
    await screen.findByText('EASY_ONLY');
    expect(screen.getByTestId('location')).not.toHaveTextContent('?view=deep');
    await user.click(screen.getByRole('button', { name: 'Browser back' }));
    await screen.findByText('PREVIOUS_PAGE');
  });

  it('opens a copied detailed URL directly and restores it on remount', async () => {
    const first = mount('/blog/example-paper?view=deep');
    await screen.findByText('DEEP_ONLY');
    first.unmount();
    mount('/blog/example-paper?view=deep');
    await screen.findByText('DEEP_ONLY');
    expect(screen.getByRole('link', { name: /쉬운 읽기/ })).toHaveAttribute('href', '/blog/example-paper');
  });

  it.each([null, '', '   \n'])('falls back without reading controls when detail is %j', async (deep) => {
    mockPost({ deep_content: deep, deep_reading_time_min: null });
    mount('/blog/example-paper?view=deep');
    await screen.findByText('EASY_ONLY');
    expect(screen.queryByRole('link', { name: /상세 읽기|쉬운 읽기/ })).not.toBeInTheDocument();
    expect(screen.getByText('5 min read')).toBeInTheDocument();
  });

  it('treats an unknown view as default', async () => {
    mount('/blog/example-paper?view=unknown');
    await screen.findByText('EASY_ONLY');
    expect(screen.getByRole('link', { name: /상세 읽기/ })).toHaveAttribute('href', '/blog/example-paper?view=deep');
  });

  it('keeps reading time useful for an old cached response without the derived field', async () => {
    mockPost({ deep_content: 'Detailed analysis. '.repeat(300), deep_reading_time_min: undefined });
    mount('/blog/example-paper?view=deep');
    await screen.findByText('3 min read');
    expect(screen.getByRole('link', { name: /쉬운 읽기/ })).toBeInTheDocument();
  });

  it('keeps canonical paper metadata and PDF navigation when detail has no Paper header', async () => {
    mockPost({ deep_content: '## 상세 방법\n\nHEADERLESS_DEEP' });
    mount('/blog/example-paper?view=deep');
    await screen.findByText('HEADERLESS_DEEP');
    expect(screen.getByRole('link', { name: /PDF 보기/ })).toHaveAttribute('href', expect.stringContaining('arxiv_id=2404.19737v1'));
    expect(document.title).toContain('2404.19737v1');
    const graph = JSON.parse(document.querySelector('script[type="application/ld+json"]')!.textContent!);
    const posting = graph['@graph'].find((node: Record<string, unknown>) => node['@type'] === 'BlogPosting');
    expect(posting.articleBody).toContain('HEADERLESS_DEEP');
    expect(posting.about['@id']).toContain('2404.19737v1');
  });

  it('keeps both editable bodies and the stable slug when editing from detailed mode', async () => {
    const user = userEvent.setup();
    vi.mocked(updateBlogPost).mockResolvedValue({ data: POST } as never);
    mount('/blog/example-paper?view=deep', true);
    await screen.findByText('DEEP_ONLY');
    await user.click(screen.getByRole('button', { name: 'Edit Post' }));
    expect(screen.getByLabelText('Content (Markdown)')).toHaveValue(EASY);
    expect(screen.getByLabelText('상세 본문 (Markdown, 선택)')).toHaveValue(DEEP);
    await user.click(screen.getByRole('button', { name: 'Save Post' }));
    await waitFor(() => expect(updateBlogPost).toHaveBeenCalledWith('paper-id', expect.objectContaining({
      slug: 'example-paper', content: EASY, deep_content: DEEP,
    })));
    await screen.findByText('DEEP_ONLY');
  });

  it('fetches both bodies before editing a list summary', async () => {
    const user = userEvent.setup();
    const summary = Object.fromEntries(Object.entries(POST).filter(([key]) => !['content', 'deep_content'].includes(key)));
    vi.mocked(fetchBlogPosts).mockResolvedValue({ data: { posts: [summary] } } as never);
    mount('/blog', true);
    await user.click(await screen.findByRole('button', { name: 'Edit post' }));
    await waitFor(() => expect(screen.getByLabelText('상세 본문 (Markdown, 선택)')).toHaveValue(DEEP));
    expect(screen.getByLabelText('Content (Markdown)')).toHaveValue(EASY);
  });

  it('ignores an older editor load that resolves after a newer selection', async () => {
    const user = userEvent.setup();
    const second = { ...POST, id: 'second', slug: 'second', title: 'Second post' };
    const summaries = [POST, second].map(p => Object.fromEntries(Object.entries(p).filter(([key]) => !['content', 'deep_content'].includes(key))));
    vi.mocked(fetchBlogPosts).mockResolvedValue({ data: { posts: summaries } } as never);
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const firstPromise = new Promise(resolve => { resolveFirst = resolve; });
    const secondPromise = new Promise(resolve => { resolveSecond = resolve; });
    vi.mocked(fetchBlogPost).mockImplementation(slug => (slug === POST.slug ? firstPromise : secondPromise) as never);
    mount('/blog', true);
    const buttons = await screen.findAllByRole('button', { name: 'Edit post' });
    await user.click(buttons[0]);
    await user.click(buttons[1]);
    await act(async () => resolveSecond({ data: second }));
    expect(screen.getByLabelText('Title')).toHaveValue('Second post');
    await act(async () => resolveFirst({ data: POST }));
    expect(screen.getByLabelText('Title')).toHaveValue('Second post');
  });
});
