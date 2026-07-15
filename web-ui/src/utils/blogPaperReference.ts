export interface BlogPaperPostLike {
  title: string;
  content: string;
  category?: string;
}

export interface BlogPaperReference {
  title: string;
  authors: string[];
  year?: number;
  arxiv_id?: string;
  doi?: string;
  url?: string;
  pdf_url?: string;
}

const PAPER_BLOCK_RE = /\*\*Paper:\*\*\s*([\s\S]*?)(?=\n\s*\*\*Abstract:\*\*|\n\s*---|\n\s*##\s|$)/i;
const ARXIV_RE = /arXiv:?\s*([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)/i;
const DOI_URL_RE = /https:\/\/doi\.org\/([^\s)]+)/i;
const DOI_TEXT_RE = /\b(?:doi|DOI):\s*(10\.\d{4,9}\/[^\s)]+)/i;
const QUOTED_TITLE_RE = /"([^"]+)"/;
const YEAR_RE = /\b((?:19|20)\d{2})\b/;

function stripTrailingPunctuation(value: string): string {
  return value.replace(/[.,;:]+$/g, '');
}

function cleanArxivId(value: string): string {
  return value.trim().replace(/[.,;:]+$/g, '');
}

function arxivBaseId(value: string): string {
  return cleanArxivId(value).replace(/v\d+$/i, '');
}

function parseAuthors(block: string): string[] {
  const beforeTitle = block.split('"')[0]?.trim();
  if (!beforeTitle) return [];
  const withoutYear = beforeTitle.replace(/\([^)]*\d{4}[^)]*\)\.?\s*$/g, '').trim();
  return withoutYear
    .split(';')
    .map((author) => author.trim())
    .filter(Boolean);
}

export function extractPrimaryPaperReference(post: BlogPaperPostLike): BlogPaperReference | null {
  const match = post.content.match(PAPER_BLOCK_RE);
  if (!match && post.category !== 'paper-review') return null;

  const block = (match?.[1] ?? post.content.slice(0, 1000)).trim();
  if (!block) return null;

  const arxivMatch = block.match(ARXIV_RE);
  const arxivId = arxivMatch ? cleanArxivId(arxivMatch[1]) : undefined;
  const doiMatch = block.match(DOI_URL_RE) ?? block.match(DOI_TEXT_RE);
  const doi = doiMatch ? stripTrailingPunctuation(doiMatch[1]) : undefined;
  const title = (block.match(QUOTED_TITLE_RE)?.[1]?.trim() || post.title).replace(/\.$/, '');
  const yearText = block.match(YEAR_RE)?.[1];
  const year = yearText ? Number(yearText) : undefined;
  const authors = parseAuthors(block);

  if (!arxivId && !doi && !title) return null;

  const ref: BlogPaperReference = { title, authors };
  if (year) ref.year = year;
  if (arxivId) {
    ref.arxiv_id = arxivId;
    ref.url = `https://arxiv.org/abs/${arxivId}`;
    ref.pdf_url = `https://arxiv.org/pdf/${arxivBaseId(arxivId)}.pdf`;
  } else if (doi) {
    ref.url = `https://doi.org/${doi}`;
  }
  if (doi) ref.doi = doi;
  return ref;
}

/**
 * SEO <title> + meta description for a blog post. Paper reviews get the
 * reviewed paper's arXiv id and a Korean "논문 리뷰" cue so the page matches how
 * people actually search; the reader-facing article headline is untouched.
 * Mirrors ``_blog_seo_meta`` in routers/seo.py so SSR and client render agree.
 */
export function blogSeoMeta(
  post: BlogPaperPostLike & { excerpt?: string },
): { title: string; description: string } {
  const base = post.title;
  const excerpt = (post.excerpt || base).trim();
  const ref = extractPrimaryPaperReference(post);
  const arxivId = ref?.arxiv_id;
  if (arxivId) {
    return {
      title: `${base} — arXiv:${arxivId} 논문 리뷰 · 집현전`,
      description: `arXiv:${arxivId} · ${excerpt}`.slice(0, 300),
    };
  }
  if (ref) {
    return { title: `${base} 논문 리뷰 · 집현전`, description: excerpt };
  }
  return { title: `${base} | Jiphyeonjeon Blog`, description: excerpt };
}

export function buildPaperViewerHref(ref: BlogPaperReference): string {
  const params = new URLSearchParams();
  params.set('title', ref.title);
  if (ref.authors.length > 0) params.set('authors', ref.authors.join(';'));
  if (ref.year) params.set('year', String(ref.year));
  if (ref.pdf_url) params.set('pdf_url', ref.pdf_url);
  if (ref.doi) params.set('doi', ref.doi);
  if (ref.arxiv_id) params.set('arxiv_id', ref.arxiv_id);
  if (ref.url) params.set('url', ref.url);
  params.set('source', 'blog-reference');
  return `/paper-viewer?${params.toString()}`;
}
