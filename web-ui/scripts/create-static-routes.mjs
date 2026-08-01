import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webUiDirectory = resolve(scriptDirectory, '..');
const sourcePath = resolve(webUiDirectory, 'dist/index.html');
const destinationPath = resolve(webUiDirectory, 'dist/introduce/index.html');

const title = 'AI 논문 검색·리뷰 도구 | 집현전 소개';
const description =
  '집현전은 arXiv·Google Scholar·OpenAlex 등에서 논문을 검색하고, 여러 논문을 AI로 비교·리뷰한 뒤 핵심 주장을 원문 근거와 대조하는 연구 도구입니다.';
const canonical = 'https://jiphyeonjeon.kr/introduce/';
const robots = 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1';

const staticContent = `
      <main data-static-route="introduce">
        <header>
          <p>Jiphyeonjeon · 집현전</p>
          <h1>논문을 찾은 뒤, 근거까지 읽습니다.</h1>
          <p>arXiv·Google Scholar·OpenAlex 등 여러 출처에서 질문에 맞는 논문을 검색하고, 여러 편을 AI로 함께 읽어 쟁점을 정리합니다. 중요한 주장은 원문 근거와 다시 대조합니다.</p>
          <p><a href="/">논문 검색 시작하기</a> · <a href="/blog/category/paper-review">공개 논문 리뷰 읽기</a></p>
        </header>
        <section>
          <h2>AI 논문 검색에서 원문 검증까지</h2>
          <ol>
            <li>질문에 맞는 논문을 여러 학술 소스에서 찾습니다.</li>
            <li>여러 논문의 공통점, 충돌, 방법론 차이를 비교합니다.</li>
            <li>핵심 주장을 원문 구절과 대조하고 인용·의역·추론·미확인을 구분합니다.</li>
            <li>인용 관계와 커리큘럼으로 다음에 읽을 논문을 정합니다.</li>
          </ol>
        </section>
        <section>
          <h2>AI 논문 검색과 리뷰, 자주 묻는 질문</h2>
          <h3>집현전은 어떤 AI 논문 검색 도구인가요?</h3>
          <p>여러 학술 검색 경로를 한곳에서 연결하고, 논문 검색 후 비교, 딥리뷰, 원문 근거 확인과 다음 읽기까지 이어가는 연구 도구입니다.</p>
          <h3>AI 논문 리뷰의 주장은 어떻게 검증하나요?</h3>
          <p>중요한 주장을 뒷받침하는 원문 구절을 찾고, 직접 인용·의역·추론·미확인을 구분해 표시합니다.</p>
          <h3>로그인 없이 무엇을 사용할 수 있나요?</h3>
          <p>논문 검색과 공개 논문 리뷰 읽기는 바로 시작할 수 있습니다. 개인 연구 공간의 리뷰·메모·북마크 저장은 로그인 후 이용합니다.</p>
        </section>
        <section id="claude">
          <h2>Claude에서 집현전 활용하기</h2>
          <p>집현전의 서비스 소개와 공개 논문 리뷰는 웹에서 바로 읽을 수 있습니다. 집현전 Agent는 웹 서비스와 별도로 설치하는 오픈소스 확장으로, Claude 대화 안에서 논문 검색·리뷰·북마크·커리큘럼 기능을 호출합니다.</p>
          <p><a href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent">집현전 Agent 설치와 소스 보기</a></p>
        </section>
        <nav aria-label="주요 페이지">
          <a href="/">논문 검색</a> · <a href="/blog">연구 블로그</a> · <a href="/blog/category/paper-review">공개 논문 리뷰</a>
        </nav>
        <footer>
          <span>© Jiphyeonjeon (집현전)</span>
          <a href="https://github.com/KimJiSeong1994" rel="me noopener noreferrer">GitHub</a>
          · <a href="https://www.linkedin.com/in/jiseong-kim-868218193/" rel="me noopener noreferrer">LinkedIn</a>
        </footer>
      </main>
`;

const replacements = [
  [/(<meta\s+name="robots"\s+content=")[^"]*("\s*\/?>)/, `$1${robots}$2`],
  [/(<meta\s+name="description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/(<link\s+rel="canonical"\s+href=")[^"]*("\s*\/?>)/, `$1${canonical}$2`],
  [/(<meta\s+property="og:title"\s+content=")[^"]*("\s*\/?>)/, `$1${title}$2`],
  [/(<meta\s+property="og:description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/(<meta\s+property="og:url"\s+content=")[^"]*("\s*\/?>)/, `$1${canonical}$2`],
  [/(<meta\s+property="og:locale"\s+content=")[^"]*("\s*\/?>)/, '$1ko_KR$2'],
  [/(<meta\s+property="og:locale:alternate"\s+content=")[^"]*("\s*\/?>)/, '$1en_US$2'],
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
    inLanguage: 'ko',
    isPartOf: { '@id': 'https://jiphyeonjeon.kr/#website' },
    about: { '@id': 'https://jiphyeonjeon.kr/#app' },
    mainEntity: { '@id': 'https://jiphyeonjeon.kr/#app' },
    publisher: { '@id': 'https://jiphyeonjeon.kr/#organization' },
  },
  {
    '@type': 'BreadcrumbList',
    '@id': `${canonical}#breadcrumb`,
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: '집현전', item: 'https://jiphyeonjeon.kr/' },
      { '@type': 'ListItem', position: 2, name: '소개', item: canonical },
    ],
  },
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

await mkdir(dirname(destinationPath), { recursive: true });
await writeFile(destinationPath, document, 'utf8');

console.log(`Created static SPA entry: ${destinationPath}`);
