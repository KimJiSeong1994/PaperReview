import { describe, expect, it } from 'vitest';
import { INTRODUCE_FAQ } from '../seo/introduceFaq';

const rawFile = (glob: Record<string, unknown>) => Object.values(glob)[0] as string;
const indexHtml = rawFile(import.meta.glob('../../index.html', { eager: true, import: 'default', query: '?raw' }));
const staticRoutes = rawFile(import.meta.glob('../../scripts/create-static-routes.mjs', { eager: true, import: 'default', query: '?raw' }));
import {
  SITE_URL,
  OG_DEFAULT_IMAGE,
  organizationNode,
  websiteNode,
  softwareApplicationNode,
  homeGraph,
  introduceGraph,
  APP_DESCRIPTION,
  APP_FEATURES,
  INTRODUCE_META,
  blogCanonical,
  blogPostingGraph,
  blogAuthorNode,
  blogIndexGraph,
  seriesGraph,
  detectLang,
  localeFor,
  type BlogPostLike,
} from '../seo/structuredData';
import { BLOG_SERIES, seriesOf } from '../seo/series';

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
    expect(node.applicationCategory).toBe('EducationalApplication');
    expect(node.operatingSystem).toBe('Web');
    expect(Array.isArray(node.featureList)).toBe(true);
    expect((node.featureList as string[]).length).toBeGreaterThan(0);
    expect(node.offers).toEqual({ '@type': 'Offer', price: '0', priceCurrency: 'USD' });
    expect(node.publisher).toEqual({ '@id': 'https://jiphyeonjeon.kr/#organization' });
  });
});

describe('introduceGraph', () => {
  it('connects the English AboutPage to the application, organization, and breadcrumb', () => {
    const graph = introduceGraph()['@graph'] as Record<string, unknown>[];
    const about = graph.find((node) => node['@type'] === 'AboutPage')!;
    const breadcrumb = graph.find((node) => node['@type'] === 'BreadcrumbList')!;

    expect(about.url).toBe('https://jiphyeonjeon.kr/introduce/');
    expect(about.inLanguage).toBe('en');
    expect(about.mainEntity).toEqual({ '@id': 'https://jiphyeonjeon.kr/#app' });
    expect(about.publisher).toEqual({ '@id': 'https://jiphyeonjeon.kr/#organization' });
    expect((breadcrumb.itemListElement as unknown[])).toHaveLength(2);
  });

  it('builds a distinct Korean AboutPage graph', () => {
    const graph = introduceGraph('ko')['@graph'] as Record<string, unknown>[];
    const about = graph.find((node) => node['@type'] === 'AboutPage')!;
    const breadcrumb = graph.find((node) => node['@type'] === 'BreadcrumbList')!;

    expect(about.url).toBe('https://jiphyeonjeon.kr/ko/introduce/');
    expect(about.inLanguage).toBe('ko');
    expect(about.name).toContain('집현전 소개');
    expect((breadcrumb.itemListElement as Record<string, unknown>[])[1].name).toBe('소개');
  });
});

describe('introduce FAQ and copies kept in sync', () => {
  it.each(['en', 'ko'] as const)('adds a FAQPage that repeats the %s FAQ word for word', (locale) => {
    const graph = introduceGraph(locale)['@graph'] as Record<string, unknown>[];
    const faq = graph.find((node) => node['@type'] === 'FAQPage')!;
    expect(faq.inLanguage).toBe(locale);
    const entities = faq.mainEntity as { name: string; acceptedAnswer: { text: string } }[];
    expect(entities.map(entity => [entity.name, entity.acceptedAnswer.text]))
      .toEqual(INTRODUCE_FAQ[locale].map(item => [item.question, item.answer]));
    expect(entities).toHaveLength(5);
  });

  it('keeps the static prerender FAQ and descriptions identical to the page', () => {
    for (const locale of ['en', 'ko'] as const) {
      for (const item of INTRODUCE_FAQ[locale]) {
        expect(staticRoutes).toContain(`'${item.question}'`);
        expect(staticRoutes).toContain(`'${item.answer}'`);
      }
    }
    // The script concatenates its description strings; compare with the pieces joined.
    const joined = staticRoutes.replace(/'\s*\n\s*\+\s*'/g, '');
    expect(joined).toContain(INTRODUCE_META.en.description);
    expect(joined).toContain(INTRODUCE_META.ko.description);
  });

  it('keeps index.html\'s WebApplication node identical to softwareApplicationNode', () => {
    const graph = JSON.parse(indexHtml.match(/<script type="application\/ld\+json" id="home-json-ld">([\s\S]*?)<\/script>/)![1]);
    const app = graph['@graph'].find((node: { '@type': string }) => node['@type'] === 'WebApplication');
    expect(app.description).toBe(APP_DESCRIPTION);
    expect(app.featureList).toEqual(APP_FEATURES);
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
  it('maps team, named, and blank bylines without fabricated profiles', () => {
    expect(blogAuthorNode(' Jiphyeonjeon Team ')).toEqual({
      '@type': 'Organization',
      '@id': 'https://jiphyeonjeon.kr/#organization',
      name: 'Jiphyeonjeon',
      alternateName: ['집현전', 'Jiphyeonjeon Team', '집현전 팀'],
      url: SITE_URL,
    });
    const organization = organizationNode();
    expect(blogAuthorNode('Jiphyeonjeon Team')).toMatchObject({
      '@id': organization['@id'],
      name: organization.name,
      alternateName: organization.alternateName,
    });
    expect(blogAuthorNode('Ada Lovelace')).toEqual({ '@type': 'Person', name: 'Ada Lovelace' });
    expect(blogAuthorNode('   ')).toBeNull();
  });

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

  it('emits a FAQPage node when the post has a 자주 묻는 질문 section', () => {
    const withFaq: BlogPostLike = {
      slug: 'gin-review',
      title: 'GIN Review',
      excerpt: 'x',
      author: 'A',
      tags: [],
      created_at: '2026-06-10T00:00:00.000Z',
      content:
        '본문.\n\n## 자주 묻는 질문\n\n### GIN 논문이란?\nGIN은 표현력을 다룬 논문입니다.\n\n' +
        '### 핵심 기여는?\nWL 테스트만큼 강력한 GNN을 증명했습니다.\n',
    };
    const nodes = blogPostingGraph(withFaq)['@graph'] as Record<string, unknown>[];
    const faq = nodes.find((n) => n['@type'] === 'FAQPage') as Record<string, unknown> | undefined;
    expect(faq).toBeDefined();
    const questions = (faq!.mainEntity as Record<string, unknown>[]).map((q) => q.name);
    expect(questions).toEqual(['GIN 논문이란?', '핵심 기여는?']);
  });

  it('omits FAQPage when there is no FAQ section', () => {
    const nodes = blogPostingGraph(samplePost)['@graph'] as Record<string, unknown>[];
    expect(nodes.some((n) => n['@type'] === 'FAQPage')).toBe(false);
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

describe('series', () => {
  it('places the systematic contextualized-embedding comparison at the end of DWE', () => {
    const slug = 'a-systematic-comparison-contextualized-word-embeddings-lexical-semantic-change';
    expect(BLOG_SERIES.dwe.slugs).toHaveLength(12);
    expect(BLOG_SERIES.dwe.slugs.at(-1)).toBe(slug);
    expect(seriesOf(slug)).toBe('dwe');
  });

  it('preserves GraphRAG method order and closes with comparative evaluation', () => {
    expect(BLOG_SERIES.graphrag.slugs).toEqual([
      'knowledge-graph-prompting-multi-document-qa',
      'ms-graphrag-global-query-focused-summarization',
      'hipporag-neurobiologically-inspired-long-term-memory',
      'lightrag-dual-level-graph-rag',
      'hipporag2-from-rag-to-memory',
      'causalrag-causal-graph-retrieval',
      'leanrag-semantic-aggregation-hierarchical-retrieval',
      'linearrag-linear-graph-retrieval-augmented-generation',
      'deep-graphrag',
      'causalrag2-hugrag-hierarchical-causal-gating',
      'ragu',
      'rag-vs-graphrag-systematic-evaluation',
    ]);
    expect(BLOG_SERIES.graphrag.slugs).toHaveLength(12);
    expect(BLOG_SERIES.graphrag.description).toContain('기초 연구부터 최초 공개 순서');
    expect(BLOG_SERIES.graphrag.description).toContain('마지막에 종합 평가');
    expect(seriesOf(BLOG_SERIES.graphrag.slugs[0])).toBe('graphrag');
    expect(seriesOf(BLOG_SERIES.graphrag.slugs.at(-1)!)).toBe('graphrag');
  });

  it('connects normalization to the modernized GNN baseline', () => {
    expect(BLOG_SERIES.gnn.slugs.slice(-2)).toEqual([
      'graphnorm',
      'classic-gnns-strong-baselines-graph-level-tasks-gnnplus-review-2026',
    ]);
    expect(seriesOf('graphnorm')).toBe('gnn');
  });

  it('separates external skills, execution, active context and attention architecture', () => {
    expect(seriesOf('agent-memory-distillation')).toBe('agent-skills');
    expect(seriesOf('skill-plus-plus')).toBe('agent-skills');
    expect(seriesOf('veriharness')).toBe('agent-harness');
    expect(seriesOf('you-dont-need-long-context')).toBe('agent-memory');
    expect(seriesOf('kimi-linear')).toBe('efficient-attention');
    for (const deferred of ['dynaflow', 'harness-aware-distillation', 'spectrag']) {
      expect(seriesOf(deferred)).toBeNull();
    }
    expect(seriesOf('hipporag2-from-rag-to-memory')).toBe('graphrag');
    expect(seriesOf('skillopt-search-policy-training-90c0bb4ee568')).toBe('jiphyeonjeon-build');
  });

  it('orders Graph causality from PCM through CIC to IC2', () => {
    const series = BLOG_SERIES['graph-causality'];
    expect(series.title).toBe('Graph causality 논문 리뷰 시리즈');
    expect(series.slugs).toEqual([
      'pcm-partial-cross-mapping-eliminates-indirect-causal-influences',
      'cic-dynamical-causality-under-invisible-confounders',
      'ic2-interventional-dynamical-causality-under-latent-confounders',
    ]);
    expect(series.description).toContain('핵심 논문을');
    expect(series.description).not.toMatch(/\d+\s*편/);
    expect(series.description).toContain('공개·기초 흐름 순서');
    expect(seriesOf(series.slugs[0])).toBe('graph-causality');
    expect(seriesOf(series.slugs.at(-1)!)).toBe('graph-causality');
  });

  it('does not assign removed urban mobility posts to a series', () => {
    expect(BLOG_SERIES['urban-spatial-sociology']).toBeUndefined();
    expect(seriesOf('transferable-human-mobility-network-reconstruction-with-neurogravity')).toBeNull();
    expect(seriesOf('theory-informed-interpretable-graph-learning-urban-commuting-flows')).toBeNull();
  });

  it('maps a member slug to its series and marks the posting isPartOf', () => {
    const memberSlug = BLOG_SERIES.gnn.slugs[0];
    expect(seriesOf(memberSlug)).toBe('gnn');
    expect(seriesOf('some-unrelated-post')).toBeNull();

    const nodes = blogPostingGraph({ ...samplePost, slug: memberSlug })[
      '@graph'
    ] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;
    expect(posting.isPartOf).toEqual({
      '@id': 'https://jiphyeonjeon.kr/blog/series/gnn#collection',
    });
  });

  it('does not mark non-member posts', () => {
    const nodes = blogPostingGraph(samplePost)['@graph'] as Record<string, unknown>[];
    const posting = nodes.find((n) => n['@type'] === 'BlogPosting')!;
    expect(posting.isPartOf).toBeUndefined();
  });
});

describe('seriesGraph', () => {
  it('emits CollectionPage with an ascending ItemList and 3-item breadcrumb', () => {
    const posts = [
      { slug: 'a-post', title: 'A' },
      { slug: 'b-post', title: 'B' },
    ];
    const nodes = seriesGraph('gnn', posts)['@graph'] as Record<string, unknown>[];
    const page = nodes.find((n) => n['@type'] === 'CollectionPage')!;
    const list = page.mainEntity as Record<string, unknown>;
    const breadcrumb = nodes.find((n) => n['@type'] === 'BreadcrumbList')!;

    expect(page['@id']).toBe('https://jiphyeonjeon.kr/blog/series/gnn#collection');
    expect(list['@type']).toBe('ItemList');
    expect(list.itemListOrder).toBe('https://schema.org/ItemListOrderAscending');
    expect(list.numberOfItems).toBe(2);
    expect(list.itemListElement).toEqual([
      { '@type': 'ListItem', position: 1, name: 'A', url: 'https://jiphyeonjeon.kr/blog/a-post' },
      { '@type': 'ListItem', position: 2, name: 'B', url: 'https://jiphyeonjeon.kr/blog/b-post' },
    ]);
    expect((breadcrumb.itemListElement as unknown[])).toHaveLength(3);
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
