// Centralized JSON-LD structured-data builders.
//
// Pure functions only — no DOM, no React. A parallel Python SSR builder must
// byte-match these shapes, so do not reorder keys or change values without
// coordinating both sides.

export const SITE_URL = 'https://jiphyeonjeon.kr';
export const OG_DEFAULT_IMAGE = `${SITE_URL}/og-default.jpg`;

const ORG_ID = 'https://jiphyeonjeon.kr/#organization';

// Shared language-detection contract — a parallel Python builder implements the
// identical rule, so do not deviate. Korean if any Hangul char is present.
const HANGUL_RE = /[가-힣ᄀ-ᇿ㄰-㆏]/;

export function detectLang(text: string): 'ko' | 'en' {
  return HANGUL_RE.test(text) ? 'ko' : 'en';
}

export function localeFor(lang: string): string {
  return lang === 'ko' ? 'ko_KR' : 'en_US';
}

export interface BlogPostLike {
  slug: string;
  title: string;
  excerpt: string;
  content: string;
  author: string;
  tags: string[];
  category?: string;
  thumbnail_url?: string;
  created_at: string;
  updated_at?: string;
}

/** Human-readable section name for a post category (used in JSON-LD articleSection). */
export function categorySection(category?: string): string {
  return category === 'paper-review' ? 'Paper Reviews' : 'Engineering';
}

export function organizationNode(): Record<string, unknown> {
  return {
    '@type': 'Organization',
    '@id': ORG_ID,
    name: 'Jiphyeonjeon',
    alternateName: '집현전',
    url: SITE_URL,
    logo: {
      '@type': 'ImageObject',
      url: `${SITE_URL}/Jiphyeonjeon_llama.png`,
    },
  };
}

export function websiteNode(): Record<string, unknown> {
  return {
    '@type': 'WebSite',
    '@id': `${SITE_URL}/#website`,
    url: SITE_URL,
    name: 'Jiphyeonjeon',
    alternateName: 'Jiphyeonjeon - Paper Graph Explorer',
    inLanguage: ['en', 'ko'],
    publisher: { '@id': ORG_ID },
  };
}

export function homeGraph(): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@graph': [organizationNode(), websiteNode()],
  };
}

export function blogCanonical(slug?: string): string {
  return slug ? `${SITE_URL}/blog/${slug}` : `${SITE_URL}/blog`;
}

export function blogBreadcrumb(title?: string, slug?: string): Record<string, unknown> {
  const itemListElement: Record<string, unknown>[] = [
    {
      '@type': 'ListItem',
      position: 1,
      name: 'Home',
      item: `${SITE_URL}/`,
    },
    {
      '@type': 'ListItem',
      position: 2,
      name: 'Blog',
      item: `${SITE_URL}/blog`,
    },
  ];

  if (title && slug) {
    itemListElement.push({
      '@type': 'ListItem',
      position: 3,
      name: title,
      item: blogCanonical(slug),
    });
  }

  return {
    '@type': 'BreadcrumbList',
    itemListElement,
  };
}

export function blogPostingGraph(post: BlogPostLike): Record<string, unknown> {
  const wordCount = post.content.trim().split(/\s+/).filter(Boolean).length;

  const posting: Record<string, unknown> = {
    '@type': 'BlogPosting',
    headline: post.title,
    description: post.excerpt,
    author: { '@type': 'Person', name: post.author },
    datePublished: post.created_at,
    dateModified: post.updated_at || post.created_at,
    keywords: post.tags,
    articleSection: categorySection(post.category),
    url: blogCanonical(post.slug),
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': blogCanonical(post.slug),
    },
    publisher: { '@id': ORG_ID },
    inLanguage: detectLang(`${post.title} ${post.content || post.excerpt || ''}`),
    wordCount,
    image: post.thumbnail_url || OG_DEFAULT_IMAGE,
  };

  return {
    '@context': 'https://schema.org',
    '@graph': [organizationNode(), posting, blogBreadcrumb(post.title, post.slug)],
  };
}

export function blogIndexGraph(
  posts: Pick<BlogPostLike, 'slug' | 'title'>[],
): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@graph': [
      organizationNode(),
      {
        '@type': 'Blog',
        '@id': `${SITE_URL}/blog#blog`,
        url: `${SITE_URL}/blog`,
        name: 'Jiphyeonjeon Blog',
        description: 'Research writeups, experiments, and product notes from Jiphyeonjeon.',
        publisher: { '@id': ORG_ID },
        blogPost: posts.slice(0, 20).map((p) => ({
          '@type': 'BlogPosting',
          headline: p.title,
          url: blogCanonical(p.slug),
        })),
      },
      blogBreadcrumb(),
    ],
  };
}
