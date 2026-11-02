import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webUiDirectory = resolve(scriptDirectory, '..');
const sourcePath = resolve(webUiDirectory, 'dist/index.html');
const destinationPath = resolve(webUiDirectory, 'dist/introduce/index.html');
const koreanDestinationPath = resolve(webUiDirectory, 'dist/ko/introduce/index.html');

const title = 'AI Paper Search & Review | About Jiphyeonjeon';
// Same text as INTRODUCE_META in src/seo/structuredData.ts (structuredData.test checks).
const description =
  'Jiphyeonjeon is an AI research assistant for papers: ask a question, get an answer '
  + 'numbered with the papers it came from across six scholarly sources, and check '
  + 'important claims against the source in a full review.';
const canonical = 'https://jiphyeonjeon.kr/introduce/';
const robots = 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1';

// Same questions and answers as src/seo/introduceFaq.ts, word for word (structuredData.test
// checks): the static FAQ and its FAQPage JSON-LD are both built from these.
const faq = {
  en: [
    ['What kind of AI paper search tool is Jiphyeonjeon?', 'It is a research assistant you ask about papers. It searches arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, and OpenAlex’s Korean-language filter, removes duplicates, and numbers each answer with the papers it came from. The results open as a relation graph and a list.'],
    ['What can I use without signing in?', 'Sample answers and public paper reviews are open without an account. Sign in, free of charge, to ask your own questions and keep your conversations.'],
    ['How are claims in an AI paper review verified?', 'In a full review. A full review finds the source passage behind each important claim and labels it as a direct quote, paraphrase, inference, or unverified. The fast review that conversations start by default summarizes within minutes but does not verify claims.'],
    ['Which sources does it search?', 'arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, and OpenAlex filtered to Korean-language papers. Coverage differs by source, so results can vary with the question and the time of the search.'],
    ['Who is Jiphyeonjeon for?', 'Researchers and graduate students entering a new field, research engineers comparing methods, and readers who need to test a paper’s claims against its evidence.'],
  ],
  ko: [
    ['집현전은 어떤 AI 논문 검색 도구인가요?', '논문에 대해 물어보면 답하는 연구 도우미입니다. arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers와 OpenAlex 한국어 논문 필터에서 찾아 중복을 걷어내고, 답변마다 근거 논문을 번호로 달아 드립니다. 결과는 관계 그래프와 목록으로 볼 수 있습니다.'],
    ['로그인 없이 무엇을 사용할 수 있나요?', '샘플 답변과 공개 논문 리뷰는 로그인 없이 볼 수 있습니다. 직접 질문하고 대화를 저장하려면 로그인하세요. 로그인 후 무료로 이용합니다.'],
    ['AI 논문 리뷰의 주장은 어떻게 검증하나요?', '정밀 리뷰에서 검증합니다. 정밀 리뷰는 중요한 주장마다 원문 구절을 찾아 직접 인용·의역·추론·미확인으로 구분합니다. 대화에서 기본으로 실행하는 빠른 리뷰는 몇 분 안에 요약하지만 주장 검증 단계는 없습니다.'],
    ['어떤 출처에서 논문을 찾나요?', 'arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers와 OpenAlex의 한국어 논문 필터를 함께 찾습니다. 출처마다 응답 범위가 달라 질문과 검색 시점에 따라 결과가 달라질 수 있습니다.'],
    ['누구에게 적합한 연구 도구인가요?', '새 주제의 핵심 논문을 찾는 연구자와 대학원생, 여러 방법론을 비교하는 리서치 엔지니어, 논문의 주장을 실제 근거와 대조해야 하는 독자에게 맞습니다.'],
  ],
};

const faqHtml = locale => faq[locale]
  .map(([question, answer]) => `          <h3>${question}</h3>\n          <p>${answer}</p>`)
  .join('\n');

const faqPage = (locale, url) => ({
  '@type': 'FAQPage',
  '@id': `${url}#faq`,
  url,
  inLanguage: locale,
  isPartOf: { '@id': `${url}#about` },
  mainEntity: faq[locale].map(([question, answer]) => ({
    '@type': 'Question',
    name: question,
    acceptedAnswer: { '@type': 'Answer', text: answer },
  })),
});

// The sample answer excerpt shown in the hero (data/samples/conversations/graphrag-vs-rag.json).
const samplePapers = [
  'Is GraphRAG Needed? From Basic RAG to Graph-/Agentic Solutions with Context Optimization (2026 · OpenAlex)',
  'RAG vs. GraphRAG: A Systematic Evaluation and Key Insights (2026 · OpenAlex)',
  'Structured Knowledge for Multi-hop QA: A Comparative Study of GraphRAG and RAG (2025 · OpenAlex)',
].map(paper => `<li>${paper}</li>`).join('');

// Both CTAs point at "/" here: a direct load of /samples needs the production nginx route.
const staticContent = `
      <main data-static-route="introduce">
        <header>
          <p>AI for paper research · free after sign-in</p>
          <h1>Find the papers. Read the evidence.</h1>
          <p>Ask about a topic or a paper title. Jiphyeonjeon searches six scholarly sources, removes duplicates, and numbers each answer with the papers it came from. Important claims are checked against the source in a full review.</p>
          <p><a href="/">Ask for free</a> · <a href="/">See a sample answer</a></p>
          <p>Sample answers and public reviews are open without signing in.</p>
        </header>
        <section>
          <h2>A conversation with Jiphyeonjeon</h2>
          <p>Sample answer · as of 2026-11-02 · translated from Korean</p>
          <p>When is GraphRAG better than standard RAG?</p>
          <p>I’ll find the relevant papers and answer with the evidence.</p>
          <ol>${samplePapers}</ol>
          <p>GraphRAG helps most when a question has to connect several clues<sup>3,8</sup>. Its strength is largest when structured knowledge or relationships inside documents matter and hallucinations must be kept down<sup>3,7,8</sup>. For simple lookup questions the gap to standard RAG is small, and building the graph is the cost<sup>2,4</sup>.</p>
        </section>
        <section id="workflow">
          <h2>What happens in one conversation</h2>
          <ol>
            <li><strong>Ask</strong> — In your own words. Write dates and conditions as part of the sentence.</li>
            <li><strong>Find</strong> — Six scholarly sources are searched and deduplicated; the results open as a graph and a list in the side panel.</li>
            <li><strong>Read</strong> — Tap a number in the answer to reach its paper. Open the PDF and get its key sentences highlighted.</li>
            <li><strong>Go deeper</strong> — A fast review takes minutes; a full review also checks claims against the source.</li>
          </ol>
          <p>Bookmarks, curricula, and daily recommendations decide what to read next.</p>
        </section>
        <section id="outputs">
          <h2>See how a claim connects to its source</h2>
          <h3>Evidence check from a full review: CausalRAG2</h3>
          <p>Review claim: The paper’s “causal gate” is not a validated directed causal edge. It is an undirected binary connection that opens a retrieval path.</p>
          <p>Source check: The method and algorithm assign neither direction nor effect size to the gate; an LLM judges causal or logical dependence.</p>
          <p>Verdict: We limit the interpretation to what the source supports.</p>
          <p><a href="/blog/causalrag2-hugrag-hierarchical-causal-gating">Read the full evidence review</a></p>
          <p><a href="/blog/category/paper-review">Browse all public reviews</a></p>
        </section>
        <section id="faq">
          <h2>Questions about AI paper search and review</h2>
${faqHtml('en')}
        </section>
        <section id="claude">
          <h2>Use Jiphyeonjeon with Claude</h2>
          <p>Jiphyeonjeon Agent is an optional open-source extension installed separately from the web app.</p>
          <p><a href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent">View installation instructions and source</a></p>
        </section>
        <section>
          <h2>Start with the paper you are curious about</h2>
          <p><a href="/">Ask for free</a> · <a href="/">See a sample answer</a></p>
        </section>
        <nav aria-label="Main pages">
          <a href="/">Home</a> · <a href="/blog">Research blog</a> · <a href="/blog/category/paper-review">Public paper reviews</a>
        </nav>
        <footer>
          <span>© Jiphyeonjeon</span>
          <a href="https://github.com/KimJiSeong1994" rel="me noopener noreferrer">GitHub</a>
          · <a href="https://www.linkedin.com/in/jiseong-kim-868218193/" rel="me noopener noreferrer">LinkedIn</a>
        </footer>
      </main>
`;

const koreanTitle = 'AI 논문 검색·리뷰 도구 | 집현전 소개';
const koreanDescription =
  '집현전은 논문에 대해 묻고 답을 받는 AI 연구 도우미입니다. 여섯 개 학술 출처에서 찾은 논문을 '
  + '번호로 달아 답하고, 정밀 리뷰에서 중요한 주장을 원문과 대조합니다.';
const koreanCanonical = 'https://jiphyeonjeon.kr/ko/introduce/';
const koreanStaticContent = `
      <main data-static-route="introduce-ko">
        <header>
          <p>논문 연구 AI · 로그인 후 무료</p>
          <h1>논문을 찾은 뒤, 근거까지 읽습니다.</h1>
          <p>궁금한 주제나 논문 제목을 물어보면 여섯 개 학술 출처에서 찾아 중복을 걷어내고, 답변마다 어느 논문에서 왔는지 번호로 달아 드립니다. 중요한 주장은 정밀 리뷰에서 원문과 다시 대조합니다.</p>
          <p><a href="/">무료로 물어보기</a> · <a href="/">샘플 답변 보기</a></p>
          <p>샘플 답변과 공개 리뷰는 로그인 없이 볼 수 있어요.</p>
        </header>
        <section>
          <h2>집현전과의 대화</h2>
          <p>2026-11-02 기준 · 상담 예시</p>
          <p>GraphRAG가 기존 RAG보다 나은 경우는 언제야?</p>
          <p>관련 논문을 찾아 근거와 함께 답해 볼게요.</p>
          <ol>${samplePapers}</ol>
          <p>GraphRAG는 질문이 여러 단서를 연결해야 할 때 더 유리합니다<sup>3,8</sup>. 특히 구조화된 지식이나 문서 내부 관계가 중요하고, 환각을 줄여야 할 때 강점이 큽니다<sup>3,7,8</sup>. 반면 단순 검색형 질문에서는 기존 RAG와 차이가 작고, 그래프 구축 비용이 문제입니다<sup>2,4</sup>.</p>
        </section>
        <section id="workflow">
          <h2>대화 한 번에 일어나는 일</h2>
          <ol>
            <li><strong>묻기</strong> — 평소 말투 그대로. 기간·조건도 문장으로 적으면 됩니다.</li>
            <li><strong>찾기</strong> — 여섯 개 학술 출처에서 찾아 중복을 걷어내고, 결과는 오른쪽 패널의 그래프와 목록으로 봅니다.</li>
            <li><strong>읽기</strong> — 답변의 번호를 누르면 근거 논문으로. PDF를 열고 핵심 문장을 자동 하이라이트합니다.</li>
            <li><strong>깊이</strong> — 빠른 리뷰는 몇 분, 정밀 리뷰는 주장을 원문과 대조하는 검증까지 합니다.</li>
          </ol>
          <p>북마크·커리큘럼·일일 추천으로 다음 읽기를 정합니다.</p>
        </section>
        <section id="outputs">
          <h2>주장과 원문이 어떻게 연결되는지 먼저 보세요</h2>
          <h3>정밀 리뷰의 검토 예시: CausalRAG2</h3>
          <p>리뷰 주장: 논문이 말하는 “인과 게이트”는 검증된 방향성 인과 간선이 아니라, 검색 경로를 여는 무방향 이진 연결입니다.</p>
          <p>원문 확인: 원문 방법과 알고리즘을 대조하면 게이트에는 방향과 효과 크기가 없고, LLM이 인과 또는 논리적 의존성을 판정합니다.</p>
          <p>판정: 원문이 뒷받침하는 범위로 해석을 제한했습니다.</p>
          <p><a href="/blog/causalrag2-hugrag-hierarchical-causal-gating">검토 과정이 담긴 리뷰 읽기</a></p>
          <p><a href="/blog/category/paper-review">공개 리뷰 전체 보기</a></p>
        </section>
        <section id="faq">
          <h2>AI 논문 검색과 리뷰, 자주 묻는 질문</h2>
${faqHtml('ko')}
        </section>
        <section id="claude">
          <h2>Claude에서 집현전 활용하기</h2>
          <p>집현전 Agent는 웹 서비스와 별도로 설치하는 오픈소스 확장입니다.</p>
          <p><a href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent">집현전 Agent 설치와 소스 보기</a></p>
        </section>
        <section>
          <h2>궁금한 논문부터 물어보세요</h2>
          <p><a href="/">무료로 물어보기</a> · <a href="/">샘플 답변 보기</a></p>
        </section>
        <nav aria-label="주요 페이지">
          <a href="/">홈</a> · <a href="/blog">연구 블로그</a> · <a href="/blog/category/paper-review">공개 논문 리뷰</a>
        </nav>
        <footer>
          <span>© Jiphyeonjeon (집현전)</span>
          <a href="https://github.com/KimJiSeong1994" rel="me noopener noreferrer">GitHub</a>
          · <a href="https://www.linkedin.com/in/jiseong-kim-868218193/" rel="me noopener noreferrer">LinkedIn</a>
        </footer>
      </main>
`;

const replacements = [
  [/<html lang="ko">/, '<html lang="en">'],
  [/(<meta\s+name="robots"\s+content=")[^"]*("\s*\/?>)/, `$1${robots}$2`],
  [/(<meta\s+name="description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/(<link\s+rel="canonical"\s+href=")[^"]*("\s*\/?>)/, `$1${canonical}$2`],
  [/(<meta\s+property="og:title"\s+content=")[^"]*("\s*\/?>)/, `$1${title}$2`],
  [/(<meta\s+property="og:description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/(<meta\s+property="og:url"\s+content=")[^"]*("\s*\/?>)/, `$1${canonical}$2`],
  [/(<meta\s+property="og:locale"\s+content=")[^"]*("\s*\/?>)/, '$1en_US$2'],
  [/(<meta\s+property="og:locale:alternate"\s+content=")[^"]*("\s*\/?>)/, '$1ko_KR$2'],
  [/(<meta\s+name="twitter:title"\s+content=")[^"]*("\s*\/?>)/, `$1${title}$2`],
  [/(<meta\s+name="twitter:description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/(<meta\s+property="og:image:alt"\s+content=")[^"]*("\s*\/?>)/, `$1${title}$2`],
  [/(<meta\s+name="twitter:image"[^>]*>)/, `$1\n    <meta name="twitter:image:alt" content="${title}" />`],
  [/<title>[^<]*<\/title>/, `<title>${title}</title>`],
];

let document = await readFile(sourcePath, 'utf8');

for (const [pattern, replacement] of replacements) {
  if (!pattern.test(document)) {
    throw new Error(`Static route generation failed: expected markup was not found: ${pattern}`);
  }
  document = document.replace(pattern, replacement);
}

const homeGraphPattern = /<script type="application\/ld\+json" id="home-json-ld">\s*([\s\S]*?)\s*<\/script>/;
const homeGraphMatch = document.match(homeGraphPattern);
if (!homeGraphMatch) {
  throw new Error('Static route generation failed: home JSON-LD graph was not found');
}

const introduceGraph = JSON.parse(homeGraphMatch[1]);
introduceGraph['@graph'].push(
  {
    '@type': 'AboutPage',
    '@id': `${canonical}#about`,
    url: canonical,
    name: title,
    description,
    inLanguage: 'en',
    isPartOf: { '@id': 'https://jiphyeonjeon.kr/#website' },
    about: { '@id': 'https://jiphyeonjeon.kr/#app' },
    mainEntity: { '@id': 'https://jiphyeonjeon.kr/#app' },
    publisher: { '@id': 'https://jiphyeonjeon.kr/#organization' },
  },
  {
    '@type': 'BreadcrumbList',
    '@id': `${canonical}#breadcrumb`,
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Jiphyeonjeon', item: 'https://jiphyeonjeon.kr/' },
      { '@type': 'ListItem', position: 2, name: 'About', item: canonical },
    ],
  },
  faqPage('en', canonical),
);
document = document.replace(
  homeGraphPattern,
  `<script type="application/ld+json" id="seo-json-ld">\n${JSON.stringify(introduceGraph, null, 2)}\n    </script>`,
);

const rootPattern = /<div id="root">[\s\S]*?<\/div>\s*(?=<\/body>)/;
if (!rootPattern.test(document)) {
  throw new Error('Static route generation failed: SPA fallback content was not found');
}
document = document.replace(rootPattern, `<div id="root">${staticContent}    </div>\n    `);
document = document.replace(
  '</head>',
  `    <link rel="alternate" hreflang="en" href="${canonical}" />\n`
  + `    <link rel="alternate" hreflang="ko" href="${koreanCanonical}" />\n`
  + `    <link rel="alternate" hreflang="x-default" href="${canonical}" />\n  </head>`,
);

await mkdir(dirname(destinationPath), { recursive: true });
await writeFile(destinationPath, document, 'utf8');

console.log(`Created static SPA entry: ${destinationPath}`);

const koreanReplacements = [
  [/(<meta\s+name="robots"\s+content=")[^"]*("\s*\/?>)/, `$1${robots}$2`],
  [/(<meta\s+name="description"\s+content=")[^"]*("\s*\/?>)/, `$1${koreanDescription}$2`],
  [/(<link\s+rel="canonical"\s+href=")[^"]*("\s*\/?>)/, `$1${koreanCanonical}$2`],
  [/(<meta\s+property="og:title"\s+content=")[^"]*("\s*\/?>)/, `$1${koreanTitle}$2`],
  [/(<meta\s+property="og:description"\s+content=")[^"]*("\s*\/?>)/, `$1${koreanDescription}$2`],
  [/(<meta\s+property="og:url"\s+content=")[^"]*("\s*\/?>)/, `$1${koreanCanonical}$2`],
  [/(<meta\s+property="og:locale"\s+content=")[^"]*("\s*\/?>)/, '$1ko_KR$2'],
  [/(<meta\s+property="og:locale:alternate"\s+content=")[^"]*("\s*\/?>)/, '$1en_US$2'],
  [/(<meta\s+name="twitter:title"\s+content=")[^"]*("\s*\/?>)/, `$1${koreanTitle}$2`],
  [/(<meta\s+name="twitter:description"\s+content=")[^"]*("\s*\/?>)/, `$1${koreanDescription}$2`],
  [/(<meta\s+property="og:image:alt"\s+content=")[^"]*("\s*\/?>)/, `$1${koreanTitle}$2`],
  [/(<meta\s+name="twitter:image"[^>]*>)/, `$1\n    <meta name="twitter:image:alt" content="${koreanTitle}" />`],
  [/<title>[^<]*<\/title>/, `<title>${koreanTitle}</title>`],
];

let koreanDocument = await readFile(sourcePath, 'utf8');
for (const [pattern, replacement] of koreanReplacements) {
  if (!pattern.test(koreanDocument)) {
    throw new Error(`Korean static route generation failed: expected markup was not found: ${pattern}`);
  }
  koreanDocument = koreanDocument.replace(pattern, replacement);
}

const koreanHomeGraphMatch = koreanDocument.match(homeGraphPattern);
if (!koreanHomeGraphMatch) {
  throw new Error('Korean static route generation failed: home JSON-LD graph was not found');
}
const koreanGraph = JSON.parse(koreanHomeGraphMatch[1]);
koreanGraph['@graph'].push(
  {
    '@type': 'AboutPage',
    '@id': `${koreanCanonical}#about`,
    url: koreanCanonical,
    name: koreanTitle,
    description: koreanDescription,
    inLanguage: 'ko',
    isPartOf: { '@id': 'https://jiphyeonjeon.kr/#website' },
    about: { '@id': 'https://jiphyeonjeon.kr/#app' },
    mainEntity: { '@id': 'https://jiphyeonjeon.kr/#app' },
    publisher: { '@id': 'https://jiphyeonjeon.kr/#organization' },
  },
  {
    '@type': 'BreadcrumbList',
    '@id': `${koreanCanonical}#breadcrumb`,
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: '집현전', item: 'https://jiphyeonjeon.kr/' },
      { '@type': 'ListItem', position: 2, name: '소개', item: koreanCanonical },
    ],
  },
  faqPage('ko', koreanCanonical),
);
koreanDocument = koreanDocument.replace(
  homeGraphPattern,
  `<script type="application/ld+json" id="seo-json-ld">\n${JSON.stringify(koreanGraph, null, 2)}\n    </script>`,
);
koreanDocument = koreanDocument.replace(rootPattern, `<div id="root">${koreanStaticContent}    </div>\n    `);
koreanDocument = koreanDocument.replace(
  '</head>',
  `    <link rel="alternate" hreflang="en" href="${canonical}" />\n`
  + `    <link rel="alternate" hreflang="ko" href="${koreanCanonical}" />\n`
  + `    <link rel="alternate" hreflang="x-default" href="${canonical}" />\n  </head>`,
);

await mkdir(dirname(koreanDestinationPath), { recursive: true });
await writeFile(koreanDestinationPath, koreanDocument, 'utf8');
console.log(`Created static SPA entry: ${koreanDestinationPath}`);
