import { describe, expect, it } from 'vitest';
import {
  SITE_URL,
  OG_DEFAULT_IMAGE,
  organizationNode,
  websiteNode,
  softwareApplicationNode,
  homeGraph,
  blogCanonical,
  blogPostingGraph,
  blogIndexGraph,
  detectLang,
  localeFor,
  type BlogPostLike,
} from '../seo/structuredData';

const samplePost: BlogPostLike = {
  slug: 'graph-rag-notes',
  title: 'GraphRAG Notes',
  excerpt: 'A short writeup on GraphRAG.',
  content: 'word one two three four five',
  author: 'Jiphyeonjeon Team',
  tags: ['RAG', 'Graph'],
  thumbnail_url: 'https://jiphyeonjeon.kr/api/blog/thumbnail/graph-rag-notes',
  created_at: '2026-06-01T00:00:00.000Z',
  updated_at: '2026-06-05T00:00:00.000Z',
};

describe('structuredData constants', () => {
  it('exposes the canonical site URL and default OG image', () => {
    expect(SITE_URL).toBe('https://jiphyeonjeon.kr');
    expect(OG_DEFAULT_IMAGE).toBe('https://jiphyeonjeon.kr/og-default.jpg');
  });
});

describe('organizationNode', () => {
  it('emits an Organization node with the canonical @id and url', () => {
    const node = organizationNode();
    expect(node['@type']).toBe('Organization');
    expect(node['@id']).toBe('https://jiphyeonjeon.kr/#organization');
    expect(node.url).toBe(SITE_URL);
    expect(node.name).toBe('Jiphyeonjeon');
    expect(node.logo).toEqual({
      '@type': 'ImageObject',
      url: 'https://jiphyeonjeon.kr/Jiphyeonjeon_llama.png',
    });
  });

  it('grounds the entity with sameAs and a disambiguating description', () => {
    const node = organizationNode();
    expect(node.sameAs).toEqual([
      'https://github.com/KimJiSeong1994/PaperReview',
      'https://github.com/KimJiSeong1994',
      'https://www.linkedin.com/in/jiseong-kim-868218193/',
    ]);
    expect(typeof node.description).toBe('string');
    // Must disambiguate from the historical Joseon-dynasty institute for AI engines.
    expect(String(node.disambiguatingDescription)).toMatch(/not the .*institute/i);
  });
});

describe('websiteNode', () => {
  it('emits a WebSite node with the canonical @id and url', () => {
    const node = websiteNode();
    expect(node['@type']).toBe('WebSite');
    expect(node['@id']).toBe('https://jiphyeonjeon.kr/#website');
    expect(node.url).toBe(SITE_URL);
    expect(node.publisher).toEqual({ '@id': 'https://jiphyeonjeon.kr/#organization' });
  });

  it('exposes a SearchAction sitelinks-searchbox pointing at the ?q= target', () => {
    const node = websiteNode();
    const action = node.potentialAction as Record<string, unknown>;
    expect(action['@type']).toBe('SearchAction');
    expect((action.target as Record<string, unknown>).urlTemplate).toBe(
      'https://jiphyeonjeon.kr/?q={search_term_string}',
    );
    expect(action['query-input']).toBe('required name=search_term_string');
  });
});

describe('softwareApplicationNode', () => {
  it('describes the product as a free web application with a feature list', () => {
    const node = softwareApplicationNode();
    expect(node['@type']).toBe('WebApplication');
    expect(node['@id']).toBe('https://jiphyeonjeon.kr/#app');
    expect(node.operatingSystem).toBe('Web');
    expect(Array.isArray(node.featureList)).toBe(true);
    expect((node.featureList as string[]).length).toBeGreaterThan(0);
    expect(node.offers).toEqual({ '@type': 'Offer', price: '0', priceCurrency: 'USD' });
    expect(node.publisher).toEqual({ '@id': 'https://jiphyeonjeon.kr/#organization' });
  });
});

describe('homeGraph', () => {
  it('bundles the Organization, WebSite, and WebApplication nodes', () => {
    const graph = homeGraph()['@graph'] as Record<string, unknown>[];
    const types = graph.map((n) => n['@type']);
    expect(types).toEqual(['Organization', 'WebSite', 'WebApplication']);
  });
});

describe('blogCanonical', () => {
  it('returns the post URL when a slug is provided', () => {
    expect(blogCanonical('graph-rag-notes')).toBe(
      'https://jiphyeonjeon.kr/blog/graph-rag-notes',
    );
  });

  it('returns the blog index URL when no slug is provided', () => {
    expect(blogCanonical()).toBe('https://jiphyeonjeon.kr/blog');
  });
});

describe('blogPostingGraph', () => {
  it('maps post fields onto the BlogPosting node', () => {
    const graph = blogPostingGraph(samplePost);
    const nodes = graph['@graph'] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;

    expect(graph['@context']).toBe('https://schema.org');
    expect(posting.headline).toBe('GraphRAG Notes');
    expect(posting.description).toBe('A short writeup on GraphRAG.');
    expect(posting.datePublished).toBe('2026-06-01T00:00:00.000Z');
    expect(posting.dateModified).toBe('2026-06-05T00:00:00.000Z');
    expect(posting.keywords).toEqual(['RAG', 'Graph']);
    expect(posting.url).toBe('https://jiphyeonjeon.kr/blog/graph-rag-notes');
    expect(posting.wordCount).toBe(6);
    expect(posting.image).toBe(samplePost.thumbnail_url);
  });

  it('falls back to created_at and default image when fields are missing', () => {
    const minimal: BlogPostLike = {
      slug: 'minimal',
      title: 'Minimal',
      excerpt: 'x',
      content: 'only one',
      author: 'A',
      tags: [],
      created_at: '2026-06-10T00:00:00.000Z',
    };
    const nodes = blogPostingGraph(minimal)['@graph'] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;
    expect(posting.dateModified).toBe('2026-06-10T00:00:00.000Z');
    expect(posting.image).toBe(OG_DEFAULT_IMAGE);
    expect(posting.wordCount).toBe(2);
  });

  it('includes the Organization node and a 3-item BreadcrumbList', () => {
    const nodes = blogPostingGraph(samplePost)['@graph'] as Record<string, unknown>[];
    const org = nodes.find((n) => n['@type'] === 'Organization');
    const breadcrumb = nodes.find((n) => n['@type'] === 'BreadcrumbList')!;
    const items = breadcrumb.itemListElement as unknown[];

    expect(org).toBeDefined();
    expect(items).toHaveLength(3);
  });

  it('sets inLanguage to en for an English-only post', () => {
    const nodes = blogPostingGraph(samplePost)['@graph'] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;
    expect(posting.inLanguage).toBe('en');
  });

  it('links the reviewed paper via about/citation and a ScholarlyArticle node', () => {
    const reviewPost: BlogPostLike = {
      ...samplePost,
      slug: 'deepwalk-review',
      category: 'paper-review',
      content:
        '# DeepWalk Review\n\n'
        + '**Paper:** Perozzi, Bryan; Al-Rfou, Rami; Skiena, Steven. (2014). '
        + '"DeepWalk: Online Learning of Social Representations." '
        + '*KDD 2014*, arXiv:1403.6652. https://doi.org/10.1145/2623330.2623732\n\n'
        + '## Review\n\nBody text.',
    };
    const nodes = blogPostingGraph(reviewPost)['@graph'] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;
    const article = nodes.find((n) => n['@type'] === 'ScholarlyArticle')!;

    const arxivUrl = 'https://arxiv.org/abs/1403.6652';
    expect(posting.about).toEqual({ '@id': arxivUrl });
    expect(posting.citation).toEqual({ '@id': arxivUrl });
    expect(article['@id']).toBe(arxivUrl);
    expect(article.name).toBe('DeepWalk: Online Learning of Social Representations');
    expect(article.author).toEqual([
      { '@type': 'Person', name: 'Perozzi, Bryan' },
      { '@type': 'Person', name: 'Al-Rfou, Rami' },
      { '@type': 'Person', name: 'Skiena, Steven.' },
    ]);
    expect(article.sameAs).toEqual(['https://doi.org/10.1145/2623330.2623732']);
    expect(article.identifier).toEqual([
      { '@type': 'PropertyValue', propertyID: 'arXiv', value: '1403.6652' },
      { '@type': 'PropertyValue', propertyID: 'DOI', value: '10.1145/2623330.2623732' },
    ]);
    // The ScholarlyArticle sits between the posting and the breadcrumb.
    expect(nodes.map((n) => n['@type'])).toEqual([
      'Organization',
      'BlogPosting',
      'ScholarlyArticle',
      'BreadcrumbList',
    ]);
  });

  it('emits no about/citation for a post without a paper reference', () => {
    const nodes = blogPostingGraph(samplePost)['@graph'] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;
    expect(posting.about).toBeUndefined();
    expect(posting.citation).toBeUndefined();
    expect(nodes.some((n) => n['@type'] === 'ScholarlyArticle')).toBe(false);
  });

  it('sets inLanguage to ko when the post contains Korean text', () => {
    const koreanPost: BlogPostLike = {
      ...samplePost,
      slug: 'graph-rag-노트',
      title: 'GraphRAG 노트',
      content: '한국어로 작성한 본문입니다.',
    };
    const nodes = blogPostingGraph(koreanPost)['@graph'] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;
    expect(posting.inLanguage).toBe('ko');
  });
});

describe('detectLang', () => {
  it('returns ko when Hangul characters are present', () => {
    expect(detectLang('논문 리뷰')).toBe('ko');
    expect(detectLang('GraphRAG 노트')).toBe('ko');
  });

  it('returns en for non-Korean text', () => {
    expect(detectLang('GraphRAG Notes')).toBe('en');
    expect(detectLang('')).toBe('en');
  });
});

describe('localeFor', () => {
  it('maps ko to ko_KR and anything else to en_US', () => {
    expect(localeFor('ko')).toBe('ko_KR');
    expect(localeFor('en')).toBe('en_US');
  });
});

describe('blogIndexGraph', () => {
  it('caps blogPost entries at 20', () => {
    const posts = Array.from({ length: 25 }, (_, i) => ({
      slug: `post-${i}`,
      title: `Post ${i}`,
    }));
    const nodes = blogIndexGraph(posts)['@graph'] as Record<string, unknown>[];
    const blog = nodes.find((n) => n['@type'] === 'Blog')!;
    expect((blog.blogPost as unknown[])).toHaveLength(20);
  });

  it('emits a 2-item breadcrumb for the index', () => {
    const nodes = blogIndexGraph([])['@graph'] as Record<string, unknown>[];
    const breadcrumb = nodes.find((n) => n['@type'] === 'BreadcrumbList')!;
    expect((breadcrumb.itemListElement as unknown[])).toHaveLength(2);
  });
});
