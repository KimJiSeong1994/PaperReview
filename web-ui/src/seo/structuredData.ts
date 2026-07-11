// Centralized JSON-LD structured-data builders.
//
// Pure functions only — no DOM, no React. A parallel Python SSR builder must
// byte-match these shapes, so do not reorder keys or change values without
// coordinating both sides.

import {
  extractPrimaryPaperReference,
  type BlogPaperReference,
} from '../utils/blogPaperReference';
import { BLOG_SERIES, seriesOf } from './series';

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
    description:
      'AI-powered academic paper search and multi-agent deep-review web app for '
      + 'researchers, covering arXiv, Google Scholar and OpenAlex.',
    disambiguatingDescription:
      'A modern AI research tool; not the 15th-century Joseon-dynasty royal '
      + 'research institute of the same name (the Hall of Worthies).',
    sameAs: [
      'https://github.com/KimJiSeong1994/PaperReview',
      'https://github.com/KimJiSeong1994',
      'https://www.linkedin.com/in/jiseong-kim-868218193/',
    ],
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
    // Sitelinks searchbox — the ?q= target is read by SearchPage.
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${SITE_URL}/?q={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    },
  };
}

/** WebApplication node describing what the product actually does (GEO). */
export function softwareApplicationNode(): Record<string, unknown> {
  return {
    '@type': 'WebApplication',
    '@id': `${SITE_URL}/#app`,
    name: 'Jiphyeonjeon',
    url: SITE_URL,
    applicationCategory: 'EducationApplication',
    operatingSystem: 'Web',
    inLanguage: ['en', 'ko'],
    featureList: [
      'Academic paper search across arXiv, Google Scholar, and OpenAlex',
      'Multi-agent deep paper review',
      'Study curriculum builder',
      'Citation graph explorer',
    ],
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    publisher: { '@id': ORG_ID },
  };
}

export function homeGraph(): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@graph': [organizationNode(), websiteNode(), softwareApplicationNode()],
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

/** ScholarlyArticle node for the paper a review is about (keep in byte-sync with seo.py). */
function scholarlyArticleNode(ref: BlogPaperReference & { url: string }): Record<string, unknown> {
  const node: Record<string, unknown> = {
    '@type': 'ScholarlyArticle',
    '@id': ref.url,
    name: ref.title,
  };
  if (ref.authors.length > 0) {
    node.author = ref.authors.map((name) => ({ '@type': 'Person', name }));
  }
  const identifiers: Record<string, unknown>[] = [];
  if (ref.arxiv_id) {
    identifiers.push({ '@type': 'PropertyValue', propertyID: 'arXiv', value: ref.arxiv_id });
  }
  if (ref.doi) {
    identifiers.push({ '@type': 'PropertyValue', propertyID: 'DOI', value: ref.doi });
    if (ref.arxiv_id) {
      node.sameAs = [`https://doi.org/${ref.doi}`];
    }
  }
  if (identifiers.length > 0) {
    node.identifier = identifiers;
  }
  return node;
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

  const seriesId = seriesOf(post.slug);
  if (seriesId) {
    posting.isPartOf = { '@id': `${SITE_URL}/blog/series/${seriesId}#collection` };
  }

  const graph: Record<string, unknown>[] = [organizationNode(), posting];
  // Link the review to the paper it discusses so answer engines can connect
  // "what does <paper> propose?" queries to this post as a citable source.
  const ref = extractPrimaryPaperReference(post);
  if (ref?.url) {
    posting.about = { '@id': ref.url };
    posting.citation = { '@id': ref.url };
    graph.push(scholarlyArticleNode(ref as BlogPaperReference & { url: string }));
  }
  graph.push(blogBreadcrumb(post.title, post.slug));

  return { '@context': 'https://schema.org', '@graph': graph };
}

/** @graph for a series pillar page (CollectionPage + ordered ItemList). */
export function seriesGraph(
  seriesId: string,
  posts: Pick<BlogPostLike, 'slug' | 'title'>[],
): Record<string, unknown> {
  const series = BLOG_SERIES[seriesId];
  const url = `${SITE_URL}/blog/series/${seriesId}`;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      organizationNode(),
      {
        '@type': 'CollectionPage',
        '@id': `${url}#collection`,
        url,
        name: `${series.title} — Jiphyeonjeon Blog`,
        description: series.description,
        isPartOf: { '@id': `${SITE_URL}/blog#blog` },
        publisher: { '@id': ORG_ID },
        mainEntity: {
          '@type': 'ItemList',
          itemListOrder: 'https://schema.org/ItemListOrderAscending',
          numberOfItems: posts.length,
          itemListElement: posts.map((p, i) => ({
            '@type': 'ListItem',
            position: i + 1,
            name: p.title,
            url: blogCanonical(p.slug),
          })),
        },
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: `${SITE_URL}/` },
          { '@type': 'ListItem', position: 2, name: 'Blog', item: `${SITE_URL}/blog` },
          { '@type': 'ListItem', position: 3, name: series.title, item: url },
        ],
      },
    ],
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
