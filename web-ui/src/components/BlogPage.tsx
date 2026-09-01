import { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeRaw from 'rehype-raw';
import rehypeSlug from 'rehype-slug';
import rehypeKatex from 'rehype-katex';
import './BlogPage.css';
import SEOHead from './SEOHead';
import BlogTableOfContents, { BODY_TOC_HEADINGS } from './BlogTableOfContents';
import ThemeToggle from './ThemeToggle';
import {
  SITE_URL,
  blogCanonical,
  blogPostingGraph,
  blogIndexGraph,
  detectLang,
  localeFor,
  OG_DEFAULT_IMAGE,
} from '../seo/structuredData';
import {
  fetchBlogPosts,
  fetchBlogPost,
  createBlogPost,
  updateBlogPost,
  deleteBlogPost,
} from '../api/client';
import { blogSeoMeta, buildPaperViewerHref, extractPrimaryPaperReference } from '../utils/blogPaperReference';
import { BLOG_SERIES, seriesOf } from '../seo/series';

// ── Types ─────────────────────────────────────────────────────────────

interface BlogPost {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  content: string;
  author: string;
  tags: string[];
  category?: string;
  thumbnail_url?: string | null;
  /** Body excerpt around the match — set by the API only for `?q=` body hits. */
  snippet?: string | null;
  reading_time_min: number;
  created_at: string;
  updated_at: string;
}

interface BlogPageProps {
  isAdmin: boolean;
  slug?: string;
  /** Set by the /blog/category/:category route to open the list pre-filtered. */
  initialCategory?: 'paper-review' | 'engineering';
}

type BlogView = 'list' | 'detail' | 'editor';

// ── Categories ────────────────────────────────────────────────────────

type CategoryKey = 'paper-review' | 'engineering';
type CategoryFilter = CategoryKey;
const DEFAULT_CATEGORY: CategoryKey = 'engineering';

/** Posts per list page, and how many page numbers the pager shows at once. */
const PAGE_SIZE = 5;
const PAGE_WINDOW = 5;

/** The visible slice of page numbers, sliding to keep `page` in the middle. */
function pageWindow(page: number, pageCount: number): number[] {
  const start = Math.max(1, Math.min(page - Math.floor(PAGE_WINDOW / 2), pageCount - PAGE_WINDOW + 1));
  return Array.from({ length: Math.min(PAGE_WINDOW, pageCount) }, (_, i) => start + i);
}

/** The sticky table of contents only renders above this width. */
const TOC_VIEWPORT_QUERY = '(min-width: 1200px)';

const CATEGORY_META: Record<CategoryKey, { label: string; badge: string }> = {
  'paper-review': { label: 'Paper Reviews', badge: 'Paper Review' },
  engineering: { label: 'Engineering', badge: 'Engineering' },
};

const SEGMENTS: { key: CategoryFilter; label: string }[] = [
  { key: 'engineering', label: 'Engineering' },
  { key: 'paper-review', label: 'Paper Reviews' },
];

/** Coerce any stored/legacy value to a known category (defaults to engineering). */
function normalizeCategory(category?: string): CategoryKey {
  return category === 'paper-review' ? 'paper-review' : 'engineering';
}

// Drop a leading top-level "# " heading so the rendered body doesn't duplicate
// the post title <h1>. Mirrors routers/seo.py::_strip_leading_h1.
const LEADING_H1_RE = /^\s*#[ \t]+[^\n]*\n+/;
function stripLeadingH1(content: string): string {
  return content.replace(LEADING_H1_RE, '');
}

// The stripped leading H1 is a Korean subtitle ("SDNE 심층 분석: … 논문 해설").
// Surface it as a Korean <h2> dek. Mirrors routers/seo.py::_leading_h1_text.
function leadingH1Text(content: string): string {
  const m = (content || '').match(/^\s*#[ \t]+([^\n]+)/);
  return m ? m[1].trim() : '';
}

// Blog paper reviews have historically used LaTeX delimiters from source
// notes (\(...\) and \[...\]). remark-math/KaTeX expects dollar
// delimiters, while Markdown parsers treat the backslashes as escapes and can
// render broken text like `(\tilde A)` instead of math. Normalize before
// handing content to ReactMarkdown so both new and legacy posts render math.
function repairCorruptedLatexEscapes(content: string): string {
  // Repair JSON escape damage where LaTeX `\tilde` was stored as tab + `ilde`.
  return content.replaceAll('\t' + 'ilde', '\\tilde');
}

function normalizeDisplayMathFences(content: string): string {
  // remark-math parses display math most reliably when both $$ fences start at
  // column zero. PaperWiki often indents \[...\] inside list items; after the
  // delimiter conversion that used to leave only the opening $$ indented, so
  // remark-math paired the closing fence with a later equation and swallowed
  // whole sections of the post as one KaTeX error.
  return content.replace(
    /^[ \t]*\$\$([\s\S]*?)\$\$[ \t]*$/gm,
    (_match, expr: string) => `$$\n${expr.trim()}\n$$`,
  );
}

function normalizeLatexDelimiters(content: string): string {
  return content
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, expr: string) => `$$${expr.trim()}$$`)
    .replace(/\\\(([^\n]*?)\\\)/g, (_match, expr: string) => `$${expr.trim()}$`);
}


function normalizeBlogMarkdown(content: string): string {
  return normalizeDisplayMathFences(normalizeLatexDelimiters(stripLeadingH1(repairCorruptedLatexEscapes(content))));
}

// Mirrors routers/blog.py::list_posts — whitespace split, capped at
// _MAX_SEARCH_TOKENS — so what we highlight is exactly what the server matched.
const MAX_SEARCH_TOKENS = 8;
const REGEX_SPECIAL_RE = /[.*+?^${}()|[\]\\]/g;

function searchTokensOf(query: string): string[] {
  return query.split(/\s+/).filter(Boolean).slice(0, MAX_SEARCH_TOKENS);
}

/** Wrap every token occurrence in <mark>, as nodes (never dangerouslySetInnerHTML). */
function highlight(text: string, tokens: string[]): React.ReactNode {
  if (!tokens.length || !text) return text;
  const pattern = new RegExp(`(${tokens.map((t) => t.replace(REGEX_SPECIAL_RE, '\\$&')).join('|')})`, 'gi');
  // split() with a capturing group interleaves the matches at the odd indices.
  return text.split(pattern).map((part, i) => (i % 2 === 1 ? <mark key={i}>{part}</mark> : part));
}

function categoryHref(key: CategoryFilter): string {
  return key === DEFAULT_CATEGORY ? '/blog' : `/blog/category/${key}`;
}

function CategoryBadge({ category }: { category?: string }) {
  const key = normalizeCategory(category);
  return (
    <span className={`blog-cat-badge blog-cat-${key}`}>
      {key === 'paper-review' ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="11" height="11" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="11" height="11" aria-hidden="true">
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      )}
      {CATEGORY_META[key].badge}
    </span>
  );
}

// renderMarkdown replaced by ReactMarkdown component (XSS-safe)

// ── Helpers ───────────────────────────────────────────────────────────

const BLOG_TITLE = 'Jiphyeonjeon Blog - Paper Research Notes';
const BLOG_DESCRIPTION = 'Research writeups, experiments, and product notes from Jiphyeonjeon.';

function formatDate(isoString: string): string {
  try {
    return new Date(isoString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  } catch {
    return isoString;
  }
}

/** Ask the figure endpoint for a resized copy; leave any other URL alone. */
function figureSrc(url: string, width: number): string {
  if (!url.includes('/api/blog/figures/')) return url;
  return `${url}${url.includes('?') ? '&' : '?'}w=${width}`;
}

/** Tag counts over the already-fetched posts, merged across casing.
 *  Mirrors routers/blog.py::_merged_tag_counts — most-used casing wins, ties
 *  by the lexicographically first — so a chip here and one on /blog/tags are
 *  the same chip, pointing at the same case-insensitive ?tag=. */
function mergedTagCounts(posts: BlogPost[]): { tag: string; count: number }[] {
  const variants = new Map<string, Map<string, number>>();
  for (const post of posts) {
    for (const tag of post.tags) {
      const key = tag.toLowerCase();
      const bucket = variants.get(key) ?? new Map<string, number>();
      bucket.set(tag, (bucket.get(tag) ?? 0) + 1);
      variants.set(key, bucket);
    }
  }
  return [...variants.values()]
    .map((bucket) => {
      const casings = [...bucket.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
      return { tag: casings[0][0], count: casings.reduce((sum, [, n]) => sum + n, 0) };
    })
    .sort((a, b) => b.count - a.count || a.tag.toLowerCase().localeCompare(b.tag.toLowerCase()));
}

function buildSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 80);
}

// Mirrors _estimate_reading_time in routers/blog.py — keep the two in sync.
const CJK_RE = /[가-힣぀-ヿ一-鿿]/g;

function estimateReadingTime(content: string): number {
  const cjkCount = (content.match(CJK_RE) || []).length;
  const words = content.replace(CJK_RE, ' ').trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.ceil((words + cjkCount / 2.5) / 200));
}

function getErrorMessage(err: unknown, fallback: string): string {
  const maybe = err as { response?: { data?: { detail?: string } }; message?: string };
  return maybe.response?.data?.detail ?? maybe.message ?? fallback;
}

// ── Loading Skeleton ──────────────────────────────────────────────────

function BlogSkeletonCard() {
  return (
    <div className="blog-skeleton-card">
      <div className="blog-skeleton-body">
        <div className="blog-skeleton-line chips" />
        <div className="blog-skeleton-line title" />
        <div className="blog-skeleton-line full" />
        <div className="blog-skeleton-line excerpt" />
      </div>
      <div className="blog-skeleton-thumb" />
    </div>
  );
}

// ── Empty editor form state ───────────────────────────────────────────

interface EditorForm {
  title: string;
  excerpt: string;
  content: string;
  author: string;
  tags: string;
  category: CategoryKey;
  thumbnail_url: string;
}

const EMPTY_FORM: EditorForm = {
  title: '',
  excerpt: '',
  content: '',
  author: '',
  tags: '',
  category: 'engineering',
  thumbnail_url: '',
};

// ── Main Component ────────────────────────────────────────────────────

function BlogPage({ isAdmin, slug, initialCategory }: BlogPageProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [view, setView] = useState<BlogView>('list');
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [activeCategory, setActiveCategory] = useState<CategoryFilter>(initialCategory ?? DEFAULT_CATEGORY);
  const [selectedPost, setSelectedPost] = useState<BlogPost | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // True only when the API definitively said the post is gone (404/410).
  const [postNotFound, setPostNotFound] = useState(false);

  // Editor state (admin only)
  const [editingPost, setEditingPost] = useState<BlogPost | null>(null);
  const [form, setForm] = useState<EditorForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Search lives entirely in an overlay: `searchInput` is what the user typed,
  // `query` is the debounced value that is actually fetched and mirrored to ?q=.
  // Landing on /blog?q=foo opens the overlay pre-filled so a shared search link
  // still works — a reach we keep over toss, which has no searchable URL.
  // A tag chip from /blog/tags lands here as ?tag=. Assumed never combined
  // with ?q= — the search overlay owns that param on its own.
  const tagFilter = searchParams.get('tag') ?? '';

  const initialQuery = searchParams.get('q') ?? '';
  const [searchOpen, setSearchOpen] = useState(Boolean(initialQuery) && !slug);
  const [searchInput, setSearchInput] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery.trim());
  const [searchResults, setSearchResults] = useState<BlogPost[] | null>(null);
  const [searching, setSearching] = useState(false);
  // Hero carousel position. Manual only — no autoplay, so there is no timer to
  // pause for prefers-reduced-motion and nothing moves under a reader's focus.
  const [heroIndex, setHeroIndex] = useState(0);

  // The sticky table of contents is a wide-screen affordance only: below
  // 1200px the article gets the full column and the body's own 목차 stands in.
  const [isWideViewport, setIsWideViewport] = useState(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(TOC_VIEWPORT_QUERY).matches
      : false,
  );
  // Focus returns here when the overlay closes.
  const searchTriggerRef = useRef<HTMLButtonElement>(null);
  // Kept separate from `error`: sharing one slot let a failed search leave a
  // permanent banner after clearing, and let a load-all failure make a
  // successful empty search read as "검색을 완료하지 못했습니다".
  const [searchError, setSearchError] = useState<string | null>(null);
  const searchTokens = useMemo(() => searchTokensOf(query), [query]);

  // ── Data fetching ──────────────────────────────────────────────────

  const loadPosts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch the full set (both categories) so the segmented control can
      // show accurate counts and switch tabs client-side without refetching.
      // With ?tag= the server narrows it first; the category tabs then filter
      // that already-narrowed set client-side, exactly as before.
      const response = await fetchBlogPosts(tagFilter || undefined, undefined, 1, 100);
      setPosts((response.data?.posts ?? response.data) as BlogPost[]);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load posts.'));
      // Fall back to empty list so UI is usable
      setPosts([]);
    } finally {
      setLoading(false);
    }
  }, [tagFilter]);

  // Debounce typing, then publish the query and mirror it to ?q=. Replace rather
  // than push so the back button doesn't step through every keystroke.
  useEffect(() => {
    const next = searchInput.trim();
    if (next === query) return;
    const timer = setTimeout(() => {
      setQuery(next);
      setSearchParams(next ? { q: next } : {}, { replace: true });
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, query, setSearchParams]);

  // Closing drops the query synchronously rather than letting the debounce do
  // it, so ?q= and the results clear the instant the overlay goes away.
  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    setSearchInput('');
    setQuery('');
    setSearchParams({}, { replace: true });
    searchTriggerRef.current?.focus();
  }, [setSearchParams]);

  // Escape-to-close and body scroll lock, both only while the overlay is up.
  useEffect(() => {
    if (!searchOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeSearch();
    };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [searchOpen, closeSearch]);

  // Body matches can't be done client-side (the list response carries no
  // content), so an active query is always a server round-trip.
  useEffect(() => {
    if (slug) return;
    if (!query) {
      setSearchResults(null);
      setSearching(false);
      setSearchError(null);
      return;
    }
    // `cancelled` also drops a stale response that resolves after a newer one.
    let cancelled = false;
    setSearching(true);
    fetchBlogPosts(undefined, undefined, 1, 20, query)
      .then((response) => {
        if (cancelled) return;
        setSearchResults((response.data?.posts ?? response.data) as BlogPost[]);
        setSearchError(null);
      })
      .catch(() => {
        if (cancelled) return;
        // A failed request must not masquerade as "no results" — an over-long
        // query (422) or a network error would otherwise tell the user their
        // search simply matched nothing.
        setSearchResults([]);
        setSearchError('검색에 실패했습니다. 잠시 후 다시 시도해주세요.');
      })
      .finally(() => {
        if (!cancelled) setSearching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query, slug]);

  // ── Category filtering (client-side) ───────────────────────────────

  const categoryCounts = useMemo(() => {
    const counts: Record<CategoryFilter, number> = {
      'paper-review': 0,
      engineering: 0,
    };
    for (const p of posts) counts[normalizeCategory(p.category)] += 1;
    return counts;
  }, [posts]);

  const visiblePosts = useMemo(
    () => posts.filter((p) => normalizeCategory(p.category) === activeCategory),
    [posts, activeCategory],
  );

  // Paging lives in ?page= alone, so a category tab or a tag chip — both of
  // which navigate to a bare path — resets to page 1 for free.
  const pageCount = Math.max(1, Math.ceil(visiblePosts.length / PAGE_SIZE));
  // Out of range clamps to the last page: ?page=9 on a 2-post category shows
  // posts, not an empty column.
  const page = Math.min(Math.max(1, Number(searchParams.get('page')) || 1), pageCount);
  const pagePosts = visiblePosts.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Newest first. Array.sort is stable, so posts sharing a created_at keep the
  // server's own publication tie-break instead of being reshuffled here.
  const recentPosts = useMemo(
    () => [...visiblePosts].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [visiblePosts],
  );
  // A three-slide carousel needs three slides; below that the whole list is
  // already on screen and the hero would just repeat it.
  const heroPosts = useMemo(
    () => (recentPosts.length >= 3 ? recentPosts.slice(0, 3) : []),
    [recentPosts],
  );
  // Slicing the *same* sorted array from 3 is what keeps the rail from
  // repeating the hero — the two can never overlap by construction.
  const railPosts = useMemo(
    () => (heroPosts.length ? recentPosts.slice(3, 8) : []),
    [heroPosts, recentPosts],
  );
  const topTags = useMemo(() => mergedTagCounts(posts).slice(0, 8), [posts]);

  // Keep the active filter in sync with the /blog/category/:category route.
  // Adjust-during-render (React's recommended pattern) rather than an effect,
  // so navigating between category hubs without a remount still re-filters.
  const [lastInitialCategory, setLastInitialCategory] = useState(initialCategory);
  if (initialCategory !== lastInitialCategory) {
    setLastInitialCategory(initialCategory);
    setActiveCategory(initialCategory ?? DEFAULT_CATEGORY);
  }

  useEffect(() => {
    if (slug) return;
    queueMicrotask(() => {
      void loadPosts();
    });
  }, [loadPosts, slug]);

  // Tags mostly live in one category, so the default tab is usually the empty
  // one after filtering. Land on a tab that actually has hits.
  useEffect(() => {
    if (!tagFilter || posts.length === 0) return;
    if (posts.some((p) => normalizeCategory(p.category) === activeCategory)) return;
    setActiveCategory(normalizeCategory(posts[0].category));
  }, [tagFilter, posts, activeCategory]);

  useEffect(() => {
    if (!slug) return;

    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      setSelectedPost(null);
      setPostNotFound(false);
      setView('detail');

      fetchBlogPost(slug)
        .then((response) => {
          if (cancelled) return;
          setSelectedPost(response.data as BlogPost);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          const status = (err as { response?: { status?: number } }).response?.status;
          // Only a definitive 404/410 means the post is gone. Anything else
          // (network failure, robots-blocked XHR in Google's renderer, 5xx)
          // must NOT flip the page to noindex — the server-rendered HTML is
          // the source of truth and already indexes real posts.
          setPostNotFound(status === 404 || status === 410);
          setError(getErrorMessage(err, 'Failed to load post.'));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    });

    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mediaQuery = window.matchMedia(TOC_VIEWPORT_QUERY);
    const handleChange = (event: MediaQueryListEvent) => setIsWideViewport(event.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // Tag the body's own table-of-contents heading and its list so CSS can hide
  // them on wide
  // screens, where the sticky index says the same thing. Done on the rendered
  // DOM rather than the markdown so no post content is rewritten; 목차-less
  // posts simply find nothing. Classes are cleared first because React reuses
  // heading nodes across posts.
  useLayoutEffect(() => {
    document
      .querySelectorAll('.body-toc-heading, .body-toc-list')
      .forEach((node) => node.classList.remove('body-toc-heading', 'body-toc-list'));
    if (view !== 'detail' || !selectedPost) return;
    const headings = document.querySelectorAll<HTMLElement>('.blog-detail-content h2');
    for (const heading of headings) {
      if (!BODY_TOC_HEADINGS.has(heading.textContent?.trim() ?? '')) continue;
      heading.classList.add('body-toc-heading');
      heading.nextElementSibling?.classList.add('body-toc-list');
      break;
    }
  }, [view, selectedPost]);

  // ── Detail view ────────────────────────────────────────────────────

  const openPost = async (post: BlogPost) => {
    setError(null);
    try {
      const response = await fetchBlogPost(post.slug);
      const full = response.data as BlogPost;
      setSelectedPost(full);
    } catch {
      // Use the list item if detail fetch fails
      setSelectedPost(post);
    }
    setView('detail');
    if (!slug) {
      navigate(`/blog/${post.slug}`);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const closeDetail = () => {
    setView('list');
    setSelectedPost(null);
    if (slug) {
      navigate('/blog');
    }
  };

  // ── Admin actions ──────────────────────────────────────────────────

  const openNewEditor = () => {
    setEditingPost(null);
    setForm(EMPTY_FORM);
    setSaveError(null);
    setView('editor');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const openEditEditor = (post: BlogPost, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingPost(post);
    setForm({
      title: post.title,
      excerpt: post.excerpt,
      content: post.content,
      author: post.author,
      tags: post.tags.join(', '),
      category: normalizeCategory(post.category),
      thumbnail_url: post.thumbnail_url ?? '',
    });
    setSaveError(null);
    setView('editor');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleDelete = async (post: BlogPost, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`"${post.title}" 포스트를 삭제하시겠습니까?`)) return;
    try {
      await deleteBlogPost(post.id);
      setPosts((prev) => prev.filter((p) => p.id !== post.id));
      if (selectedPost?.id === post.id) {
        setSelectedPost(null);
        setView('list');
      }
    } catch (err: unknown) {
      alert(getErrorMessage(err, '삭제 중 오류가 발생했습니다.'));
    }
  };

  const handleSave = async () => {
    if (!form.title.trim()) { setSaveError('제목을 입력해주세요.'); return; }
    if (!form.content.trim()) { setSaveError('본문을 입력해주세요.'); return; }

    setSaving(true);
    setSaveError(null);

    const payload = {
      title: form.title.trim(),
      slug: buildSlug(form.title),
      excerpt: form.excerpt.trim() || form.content.trim().slice(0, 160),
      content: form.content.trim(),
      author: form.author.trim() || '집현전 팀',
      tags: form.tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      category: form.category,
      thumbnail_url: form.thumbnail_url.trim() || undefined,
      reading_time_min: estimateReadingTime(form.content),
    };

    try {
      if (editingPost) {
        const response = await updateBlogPost(editingPost.id, payload);
        const updated = response.data as BlogPost;
        setPosts((prev) => prev.map((p) => (p.id === editingPost.id ? updated : p)));
        setSelectedPost(updated);
        setView('detail');
      } else {
        const response = await createBlogPost(payload);
        const created = response.data as BlogPost;
        setPosts((prev) => [created, ...prev]);
        setSelectedPost(created);
        setView('detail');
      }
      // Refresh tags in the background
    } catch (err: unknown) {
      setSaveError(getErrorMessage(err, '저장 중 오류가 발생했습니다.'));
    } finally {
      setSaving(false);
    }
  };

  // ── Header shared by all views ─────────────────────────────────────

  const renderHeader = () => (
    <div className="blog-app-header">
      <div className="blog-header-nav">
        <div className="blog-logo" onClick={() => navigate('/')}>
          <picture>
            <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
            <img
              src="/Jiphyeonjeon_llama.png"
              alt="Jiphyeonjeon"
              className="blog-logo-icon"
              width={128}
              height={128}
              loading="eager"
              fetchPriority="high"
              onError={(e) => { e.currentTarget.style.display = 'none'; }}
            />
          </picture>
          <span className="blog-brand-name">Jiphyeonjeon</span>
        </div>
        {/* Two categories fit the header; the series and the tag hub keep
            their own cards in the right rail so nothing is unreachable. */}
        {view === 'list' && (
          <nav className="blog-header-tabs" aria-label="카테고리">
            {SEGMENTS.map((seg) => (
              <a
                key={seg.key}
                href={categoryHref(seg.key)}
                data-cat={seg.key}
                className={`blog-header-tab${activeCategory === seg.key ? ' active' : ''}`}
                aria-current={activeCategory === seg.key ? 'page' : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  setActiveCategory(seg.key);
                  navigate(categoryHref(seg.key));
                }}
              >
                {seg.label}
                <span className="blog-header-tab-count">{categoryCounts[seg.key]}</span>
              </a>
            ))}
          </nav>
        )}
        <div className="blog-header-actions">
          {/* List view only: from a post, `openPost` deliberately skips the
              navigate() when a slug route is already mounted, so a result click
              there would swap the body without moving the URL. */}
          {view === 'list' && (
            <button
              ref={searchTriggerRef}
              className="blog-nav-btn blog-search-trigger"
              aria-label="블로그 글 검색"
              onClick={() => setSearchOpen(true)}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18" aria-hidden="true">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            </button>
          )}
          <button className="blog-nav-btn blog-nav-btn-active">Blog</button>
          <button className="blog-nav-btn" onClick={() => navigate('/')}>Search</button>
          <button className="blog-nav-btn" onClick={() => navigate('/mypage')}>My Page</button>
          <ThemeToggle />
        </div>
      </div>
    </div>
  );

  // ── Search overlay ─────────────────────────────────────────────────

  const searchResultRow = (post: BlogPost) => (
    <a
      key={post.id}
      className="blog-search-result"
      href={`/blog/${post.slug}`}
      onClick={(e) => {
        e.preventDefault();
        closeSearch();
        void openPost(post);
      }}
    >
      <span className="blog-search-result-title">{highlight(post.title, searchTokens)}</span>
      <span className="blog-search-result-snippet">
        {highlight(post.snippet ?? post.excerpt, searchTokens)}
      </span>
    </a>
  );

  const renderSearchOverlay = () => {
    const results = searchResults ?? [];
    // The render that publishes a new `query` runs before the effect that sets
    // `searching`, so without waiting for a landed response the empty state
    // flashes for one frame — and the aria-live count announces a stale 0.
    const settled = searchResults !== null && !searching;
    return (
      // Deliberately rendered inside .blog-container: every --wov-*/--indigo*
      // token is scoped to that element (and its light-mode override), so a
      // portal to <body> would strip the palette. position:fixed still escapes.
      // No click-to-close on the backdrop: the overlay is an opaque full-screen
      // takeover, so every stray click lands on it. That handler is why a shared
      // /blog?q=… link looked like it never opened — one click closed it and
      // wiped ?q= from the URL. Escape and the × button are the ways out.
      <div className="blog-search-overlay">
        <div className="blog-search-panel" role="dialog" aria-modal="true" aria-label="글 검색 창">
          <div className="blog-search-topbar">
            <span className="blog-search-brand">
              <picture>
                <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
                <img
                  src="/Jiphyeonjeon_llama.png"
                  alt="Jiphyeonjeon"
                  className="blog-search-logo"
                  width={22}
                  height={22}
                  onError={(e) => { e.currentTarget.style.display = 'none'; }}
                />
              </picture>
              Jiphyeonjeon
            </span>
            <button type="button" className="blog-search-close" aria-label="검색 닫기" onClick={closeSearch}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <input
            className="blog-search-input"
            type="search"
            autoFocus
            value={searchInput}
            placeholder="주제, 시리즈 검색"
            aria-label="검색어"
            onChange={(e) => setSearchInput(e.target.value)}
          />

          {/* toss shows no result count; screen readers still need one. */}
          <div className="blog-sr-only" role="status" aria-live="polite">
            {query && settled && !searchError ? `검색 결과 ${results.length}개` : ''}
          </div>

          <div className="blog-search-results" aria-busy={searching}>
            {searchError ? (
              // A failed request must never read as "nothing matched".
              <div className="blog-search-empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="40" height="40" aria-hidden="true">
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <div className="blog-search-empty-title">검색을 완료하지 못했습니다</div>
                <div className="blog-search-empty-sub">검색어를 줄이거나 잠시 후 다시 시도해보세요.</div>
              </div>
            ) : !query ? (
              <>
                {/* Unlabelled rows in the visual design; named for screen readers. */}
                <div className="blog-sr-only">최근 글</div>
                {posts.slice(0, 3).map(searchResultRow)}
              </>
            ) : settled && results.length === 0 ? (
              <div className="blog-search-empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="40" height="40" aria-hidden="true">
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <div className="blog-search-empty-title">검색 결과가 없어요</div>
              </div>
            ) : (
              results.map(searchResultRow)
            )}
          </div>
        </div>
      </div>
    );
  };

  const goToPage = (next: number) => {
    const params = new URLSearchParams(searchParams);
    if (next <= 1) params.delete('page');
    else params.set('page', String(next));
    setSearchParams(params);
    // Back to the top of the list, not to the pager the click came from.
    // jsdom has no scrollIntoView, hence the optional call.
    document.getElementById('all-articles')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };

  // ── Right rail (list view) ──────────────────────────────────────────

  const railLink = (href: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    navigate(href);
  };

  const renderRail = () => (
    <aside className="blog-rail">
      {railPosts.length > 0 && (
        <section className="blog-rail-card" aria-labelledby="rail-recent">
          <h2 className="blog-rail-title" id="rail-recent">최근 글</h2>
          <ol className="blog-rail-list">
            {railPosts.map((post, i) => (
              <li key={post.id} className="blog-rail-item">
                <span className="blog-rail-rank" aria-hidden="true">{i + 1}</span>
                <a
                  className="blog-rail-link"
                  href={`/blog/${post.slug}`}
                  onClick={(e) => { e.preventDefault(); void openPost(post); }}
                >
                  {post.title}
                </a>
              </li>
            ))}
          </ol>
        </section>
      )}

      {topTags.length > 0 && (
        <section className="blog-rail-card" aria-labelledby="rail-tags">
          <h2 className="blog-rail-title" id="rail-tags">인기 태그</h2>
          <div className="blog-rail-tags">
            {topTags.map(({ tag, count }) => (
              <a
                key={tag}
                className="blog-rail-tag"
                href={`/blog?tag=${encodeURIComponent(tag)}`}
                onClick={railLink(`/blog?tag=${encodeURIComponent(tag)}`)}
              >
                {tag}
                <span className="blog-rail-count">{count}</span>
              </a>
            ))}
          </div>
          <a className="blog-rail-more" href="/blog/tags" onClick={railLink('/blog/tags')}>
            태그 전체 보기
          </a>
        </section>
      )}
    </aside>
  );

  // ── Series index (page bottom, full container width) ────────────────

  const renderSeriesIndex = () => (
    <section className="blog-series-index" aria-labelledby="series-index">
      <h2 className="blog-section-heading" id="series-index">아티클 시리즈</h2>
      <div className="blog-series-grid">
        {Object.entries(BLOG_SERIES).map(([sid, series]) => {
          // Cover = the first chapter's thumbnail, looked up in the whole post
          // list: a series living in the other category still gets its image.
          const cover = posts.find((p) => p.slug === series.slugs[0])?.thumbnail_url;
          return (
            <a
              key={sid}
              className="blog-series-card"
              href={`/blog/series/${sid}`}
              onClick={railLink(`/blog/series/${sid}`)}
            >
              {/* The ground is painted by the wrapper either way, so a missing
                  or failed cover costs no height. */}
              <div className="blog-series-cover">
                {cover && (
                  <img
                    src={figureSrc(cover, 456)}
                    alt=""
                    width={190}
                    height={190}
                    loading="lazy"
                    decoding="async"
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                  />
                )}
              </div>
              <h3 className="blog-series-title">{series.title}</h3>
              <p className="blog-series-desc">{series.description}</p>
              <span className="blog-series-count">아티클 {series.slugs.length}개</span>
            </a>
          );
        })}
      </div>
    </section>
  );

  // ── Hero carousel (3 newest, manual only) ───────────────────────────

  const renderHero = () => {
    const post = heroPosts[heroIndex];
    const cat = normalizeCategory(post.category);
    const step = (delta: number) =>
      setHeroIndex((i) => (i + delta + heroPosts.length) % heroPosts.length);
    return (
      <section
        className="blog-hero"
        aria-roledescription="carousel"
        aria-label="주요 글"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowLeft') step(-1);
          else if (e.key === 'ArrowRight') step(1);
        }}
      >
        {/* Manual advance only, so polite is enough: the slide changes because
            the reader pressed a button, and the new one is announced then. */}
        <div className="blog-hero-slide" aria-live="polite">
          <div className="blog-hero-text">
            <span className="blog-row-cat" data-cat={cat}>{CATEGORY_META[cat].badge}</span>
            <h2 className="blog-hero-title">
              <a
                className="blog-hero-link"
                href={`/blog/${post.slug}`}
                onClick={(e) => { e.preventDefault(); void openPost(post); }}
              >
                {post.title}
              </a>
            </h2>
            <p className="blog-hero-excerpt">{post.excerpt}</p>
            <div className="blog-hero-controls">
              <button type="button" className="blog-hero-arrow" aria-label="이전 글" onClick={() => step(-1)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18" aria-hidden="true">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
              <button type="button" className="blog-hero-arrow" aria-label="다음 글" onClick={() => step(1)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18" aria-hidden="true">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
              <span className="blog-hero-counter" aria-hidden="true">
                {heroIndex + 1} / {heroPosts.length}
              </span>
            </div>
          </div>
          {post.thumbnail_url && (
            // Same destination as the title above it — hidden from AT so the
            // slide offers one link, not two, one of them unnamed.
            <a
              className="blog-hero-media"
              href={`/blog/${post.slug}`}
              tabIndex={-1}
              aria-hidden="true"
              onClick={(e) => { e.preventDefault(); void openPost(post); }}
            >
              <img
                src={figureSrc(post.thumbnail_url, 640)}
                alt=""
                width={520}
                height={280}
                loading="lazy"
                decoding="async"
                onError={(e) => { e.currentTarget.parentElement!.style.display = 'none'; }}
              />
            </a>
          )}
        </div>
      </section>
    );
  };

  // ── List view ──────────────────────────────────────────────────────

  const renderList = () => (
    <>
      <header className="blog-header">
        <div className="blog-title-row">
          <h1 className="blog-page-title">Blog</h1>
          {isAdmin && (
            <div className="blog-admin-bar">
              <button className="blog-new-post-btn" onClick={openNewEditor}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                New Post
              </button>
            </div>
          )}
        </div>
        <p className="blog-page-subtitle">Research writeups, experiments, and product notes.</p>
      </header>

      {tagFilter && (
        <div className="blog-tag-filter">
          <span className="blog-tag-filter-label">태그: {tagFilter}</span>
          <button
            type="button"
            className="blog-tag-filter-clear"
            aria-label="태그 필터 해제"
            onClick={() => navigate('/blog')}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      )}

      {error && <div className="blog-error">{error}</div>}

      {loading ? (
        <div className="blog-skeleton-grid">
          {[0, 1, 2, 3].map((i) => <BlogSkeletonCard key={i} />)}
        </div>
      ) : posts.length === 0 ? (
        <div className="blog-empty">
          <div className="blog-empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48" style={{ opacity: 0.3 }}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          </div>
          <div className="blog-empty-title">
            게시물이 없습니다
          </div>
          <div className="blog-empty-subtitle">
            {isAdmin ? '첫 번째 블로그 포스트를 작성해보세요.' : '곧 새로운 글이 올라올 예정입니다.'}
          </div>
        </div>
      ) : (
        <>
          {heroPosts.length > 0 && renderHero()}

          <div className="blog-layout">
            <section className="blog-main" aria-labelledby="all-articles">
              <h2 className="blog-section-heading" id="all-articles">전체 아티클</h2>
              {visiblePosts.length === 0 ? (
                <div className="blog-empty">
                  <div className="blog-empty-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48" style={{ opacity: 0.3 }}>
                      <circle cx="11" cy="11" r="8" />
                      <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </svg>
                  </div>
                  <div className="blog-empty-title">
                    {activeCategory === 'paper-review' ? '논문 리뷰 글이 아직 없습니다' : '개발 노트가 아직 없습니다'}
                  </div>
                  <div className="blog-empty-subtitle">
                    {activeCategory === 'paper-review'
                      ? '딥리뷰를 블로그 초안으로 정리하면 이곳에 모입니다.'
                      : '집현전 개발·제품 이야기가 곧 올라올 예정입니다.'}
                  </div>
                </div>
              ) : (
                <div className="blog-grid">
                  {pagePosts.map((post) => {
                    const cat = normalizeCategory(post.category);
                    return (
                      // The admin buttons are siblings of the row, not children:
                      // a <button> inside an <a> is invalid, folds into the link's
                      // accessible name, and could never be reached with Enter.
                      <div key={post.id} className="blog-row-wrap">
                        <a
                          className="blog-row"
                          href={`/blog/${post.slug}`}
                          aria-label={post.title}
                          onClick={(e) => { e.preventDefault(); void openPost(post); }}
                        >
                          <div className="blog-row-text">
                            <div className="blog-row-chips">
                              <span className="blog-row-cat" data-cat={cat}>{CATEGORY_META[cat].badge}</span>
                              <span className="blog-row-author">{post.author}</span>
                            </div>

                            <h3 className="blog-row-title">{post.title}</h3>

                            <p className="blog-row-excerpt">{post.excerpt}</p>
                          </div>

                          {/* No thumbnail is a layout case, not a missing image: the
                              text column simply takes the whole row. */}
                          {post.thumbnail_url && (
                            <div className="blog-row-thumb">
                              <img
                                src={figureSrc(post.thumbnail_url, 456)}
                                alt=""
                                width={228}
                                height={128}
                                loading="lazy"
                                decoding="async"
                                onError={(e) => { e.currentTarget.parentElement!.style.display = 'none'; }}
                              />
                            </div>
                          )}
                        </a>

                        {isAdmin && (
                          <div className="blog-card-admin-actions">
                            <button
                              className="blog-card-edit-btn"
                              onClick={(e) => openEditEditor(post, e)}
                              aria-label="Edit post"
                            >
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                              </svg>
                              Edit
                            </button>
                            <button
                              className="blog-card-delete-btn"
                              onClick={(e) => handleDelete(post, e)}
                              aria-label="Delete post"
                            >
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                                <polyline points="3 6 5 6 21 6" />
                                <path d="M19 6l-1 14H6L5 6" />
                                <path d="M10 11v6M14 11v6" />
                                <path d="M9 6V4h6v2" />
                              </svg>
                              Delete
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {pageCount > 1 && (
                <nav className="blog-pager" aria-label="페이지">
                  <button
                    type="button"
                    className="blog-page-btn"
                    aria-label="이전 페이지"
                    disabled={page <= 1}
                    onClick={() => goToPage(page - 1)}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true">
                      <polyline points="15 18 9 12 15 6" />
                    </svg>
                  </button>
                  {pageWindow(page, pageCount).map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={`blog-page-btn${n === page ? ' active' : ''}`}
                      aria-label={`${n}페이지`}
                      aria-current={n === page ? 'page' : undefined}
                      onClick={() => goToPage(n)}
                    >
                      {n}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="blog-page-btn"
                    aria-label="다음 페이지"
                    disabled={page >= pageCount}
                    onClick={() => goToPage(page + 1)}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                  </button>
                </nav>
              )}
            </section>

            {renderRail()}
          </div>

          {renderSeriesIndex()}
        </>
      )}
    </>
  );

  // ── Detail view ────────────────────────────────────────────────────

  const renderDetail = () => {
    if (!selectedPost) {
      return (
        <div className="blog-detail">
          <button className="blog-detail-back" onClick={closeDetail}>
            Back to Blog
          </button>
          {loading ? (
            <div className="blog-empty-title">Loading post...</div>
          ) : (
            <div className="blog-error">{error ?? 'Post not found.'}</div>
          )}
        </div>
      );
    }

    const paperReference = extractPrimaryPaperReference(selectedPost);
    const paperViewerHref = paperReference ? buildPaperViewerHref(paperReference) : null;

    return (
      <div className="blog-detail">
        <button className="blog-detail-back" onClick={closeDetail}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
            <line x1="19" y1="12" x2="5" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
          Back to Blog
        </button>

        <div className="blog-detail-meta">
          <CategoryBadge category={selectedPost.category} />
          <span className="blog-card-dot" aria-hidden="true" />
          <span className="blog-detail-author">{selectedPost.author}</span>
          <span className="blog-card-dot" aria-hidden="true" />
          <span>{formatDate(selectedPost.created_at)}</span>
          <span className="blog-card-dot" aria-hidden="true" />
          <span>{selectedPost.reading_time_min} min read</span>
          {paperViewerHref && (
            <a className="blog-detail-pdf-link" href={paperViewerHref} aria-label={`${paperReference?.title ?? selectedPost.title} PDF 보기`}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" aria-hidden="true">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              PDF 보기
            </a>
          )}
        </div>

        <h1 className="blog-detail-title">{selectedPost.title}</h1>

        {(() => {
          const dek = leadingH1Text(selectedPost.content);
          return dek && dek !== selectedPost.title ? (
            <h2 className="blog-detail-dek">{dek}</h2>
          ) : null;
        })()}

        {selectedPost.tags.length > 0 && (
          <div className="blog-detail-tags">
            {selectedPost.tags.map((tag) => (
              <span key={tag} className="blog-tag">{tag}</span>
            ))}
          </div>
        )}

        {selectedPost.excerpt && (
          <p className="blog-detail-lead">{selectedPost.excerpt}</p>
        )}

        {(() => {
          const seriesId = seriesOf(selectedPost.slug);
          if (!seriesId) return null;
          const series = BLOG_SERIES[seriesId];
          const position = series.slugs.indexOf(selectedPost.slug) + 1;
          const prevSlug = position > 1 ? series.slugs[position - 2] : null;
          const nextSlug = position < series.slugs.length ? series.slugs[position] : null;
          return (
            <nav className="blog-series" aria-label="Series">
              <a href={`/blog/series/${seriesId}`}>{series.title}</a>
              {` · ${position}/${series.slugs.length}편`}
              {prevSlug && <a rel="prev" href={`/blog/${prevSlug}`}>← 시리즈 이전 글</a>}
              {nextSlug && <a rel="next" href={`/blog/${nextSlug}`}>시리즈 다음 글 →</a>}
            </nav>
          );
        })()}

        <div className="blog-detail-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeRaw, rehypeSlug, rehypeKatex]}
          >
            {normalizeBlogMarkdown(selectedPost.content)}
          </ReactMarkdown>
        </div>

        {isAdmin && (
          <div className="blog-detail-admin-bar">
            <button
              className="blog-card-edit-btn"
              onClick={(e) => openEditEditor(selectedPost, e)}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Edit Post
            </button>
            <button
              className="blog-card-delete-btn"
              onClick={(e) => handleDelete(selectedPost, e)}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6l-1 14H6L5 6" />
                <path d="M10 11v6M14 11v6" />
                <path d="M9 6V4h6v2" />
              </svg>
              Delete Post
            </button>
          </div>
        )}
      </div>
    );
  };

  // ── Editor view (admin) ────────────────────────────────────────────

  const renderEditor = () => (
    <div className="blog-editor">
      <div className="blog-editor-header">
        <span className="blog-editor-title-text">
          {editingPost ? 'Edit Post' : 'New Post'}
        </span>
        <div className="blog-editor-actions">
          <button
            className="blog-editor-cancel-btn"
            onClick={() => {
              if (editingPost && selectedPost) {
                setView('detail');
              } else {
                setView('list');
              }
            }}
          >
            Cancel
          </button>
          <button
            className="blog-editor-save-btn"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" style={{ animation: 'spin 1s linear infinite' }}>
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
                Saving...
              </>
            ) : (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                  <polyline points="17 21 17 13 7 13 7 21" />
                  <polyline points="7 3 7 8 15 8" />
                </svg>
                Save Post
              </>
            )}
          </button>
        </div>
      </div>

      {saveError && <div className="blog-error">{saveError}</div>}

      <div className="blog-editor-form">
        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-title">Title</label>
          <input
            id="blog-field-title"
            className="blog-editor-input"
            type="text"
            placeholder="Post title..."
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label">Category</label>
          <div className="blog-editor-segments" role="radiogroup" aria-label="Post category">
            {(Object.keys(CATEGORY_META) as CategoryKey[]).map((key) => (
              <button
                key={key}
                type="button"
                role="radio"
                data-cat={key}
                aria-checked={form.category === key}
                className={`blog-editor-segment ${form.category === key ? 'active' : ''}`}
                onClick={() => setForm((f) => ({ ...f, category: key }))}
              >
                {CATEGORY_META[key].badge}
              </button>
            ))}
          </div>
          <span className="blog-editor-hint">
            'Paper Review'는 논문 리뷰 섹션, 'Engineering'은 개발·제품 노트 섹션으로 묶입니다.
          </span>
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-excerpt">Excerpt</label>
          <input
            id="blog-field-excerpt"
            className="blog-editor-input"
            type="text"
            placeholder="Short description shown in the card list..."
            value={form.excerpt}
            onChange={(e) => setForm((f) => ({ ...f, excerpt: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-author">Author</label>
          <input
            id="blog-field-author"
            className="blog-editor-input"
            type="text"
            placeholder="Author name (default: 집현전 팀)"
            value={form.author}
            onChange={(e) => setForm((f) => ({ ...f, author: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-tags">Tags</label>
          <input
            id="blog-field-tags"
            className="blog-editor-input"
            type="text"
            placeholder="Comma-separated tags: AI, Research, NLP"
            value={form.tags}
            onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-thumb">Thumbnail URL</label>
          <input
            id="blog-field-thumb"
            className="blog-editor-input"
            type="text"
            placeholder="https://... (leave blank for gradient placeholder)"
            value={form.thumbnail_url}
            onChange={(e) => setForm((f) => ({ ...f, thumbnail_url: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-content">Content (Markdown)</label>
          <textarea
            id="blog-field-content"
            className="blog-editor-textarea"
            placeholder={`# Section Title\n\nWrite your post content in Markdown...\n\n## Sub-section\n\nParagraph text here.`}
            value={form.content}
            onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
          />
          <span className="blog-editor-hint">
            Supports: # headings, **bold**, *italic*, `code`, - lists, 1. ordered lists, {'>'} blockquote, ``` code blocks
          </span>
        </div>
      </div>
    </div>
  );

  // ── Render ─────────────────────────────────────────────────────────

  const seoPost = view === 'detail' ? selectedPost : null;
  const categoryView = view === 'list';
  const categoryLabel = categoryView ? CATEGORY_META[activeCategory].label : '';
  const seoMeta = seoPost ? blogSeoMeta(seoPost) : null;
  const seoTitle = seoMeta
    ? seoMeta.title
    : categoryView
      ? `${categoryLabel} | Jiphyeonjeon Blog`
      : BLOG_TITLE;
  const seoDescription = seoMeta ? seoMeta.description : BLOG_DESCRIPTION;
  const hasSlugError = Boolean(slug && view === 'detail' && !loading && !seoPost && postNotFound);
  const listCanonical = initialCategory
    ? `${SITE_URL}/blog/category/${activeCategory}`
    : blogCanonical(hasSlugError ? undefined : slug);
  const seoCanonical = seoPost
    ? blogCanonical(seoPost.slug)
    // Each page lists a different slice, so collapsing them to page 1 would
    // drop pages 2..n from the index.
    : categoryView && page > 1
      ? `${listCanonical}?page=${page}`
      : listCanonical;
  const seoLocale = seoPost
    ? localeFor(detectLang(`${seoPost.title} ${seoPost.content || seoPost.excerpt || ''}`))
    : undefined;

  return (
    <div className="blog-container">
      <SEOHead
        title={seoTitle}
        description={seoDescription}
        canonical={seoCanonical}
        robots={hasSlugError || (categoryView && (query || tagFilter)) ? 'noindex,nofollow' : undefined}
        type={seoPost ? 'article' : 'website'}
        image={seoPost ? seoPost.thumbnail_url || OG_DEFAULT_IMAGE : undefined}
        publishedTime={seoPost ? seoPost.created_at : undefined}
        modifiedTime={seoPost ? seoPost.updated_at || seoPost.created_at : undefined}
        locale={seoLocale}
        jsonLd={seoPost ? blogPostingGraph(seoPost) : blogIndexGraph(posts)}
      />
      {renderHeader()}
      {searchOpen && renderSearchOverlay()}
      <div className={`blog-content${view === 'list' ? ' blog-content--list' : ''}`}>
        {view === 'list' && renderList()}
        {view === 'detail' && (
          <div className="blog-detail-layout">
            {renderDetail()}
            {isWideViewport && selectedPost && <BlogTableOfContents postKey={selectedPost.slug} />}
          </div>
        )}
        {view === 'editor' && isAdmin && renderEditor()}
      </div>
    </div>
  );
}

export default BlogPage;
