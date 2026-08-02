import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webUiDirectory = resolve(scriptDirectory, '..');
const sourcePath = resolve(webUiDirectory, 'dist/index.html');
const destinationPath = resolve(webUiDirectory, 'dist/introduce/index.html');

const title = 'AI Paper Search & Review | About Jiphyeonjeon';
const description =
  'Jiphyeonjeon searches scholarly sources, compares papers in an AI deep review, and checks important claims against source passages before guiding the next read.';
const canonical = 'https://jiphyeonjeon.kr/introduce/';
const robots = 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1';

const staticContent = `
      <main data-static-route="introduce">
        <header>
          <p>Jiphyeonjeon</p>
          <h1>Find the papers. Read the evidence.</h1>
          <p>Search arXiv, Google Scholar, OpenAlex, and other scholarly sources for papers that match your question. Compare multiple papers with AI, then check important claims against the original passages.</p>
          <p><a href="/">Search papers</a> · <a href="/blog/category/paper-review">Read public reviews</a></p>
        </header>
        <section>
          <h2>From paper search to source verification</h2>
          <ol>
            <li>Find papers that match your question across scholarly sources.</li>
            <li>Compare agreements, conflicts, and methodological differences.</li>
            <li>Check key claims against source passages and distinguish quotation, paraphrase, inference, and unverified statements.</li>
            <li>Use citation relationships and a curriculum to decide what to read next.</li>
          </ol>
        </section>
        <section>
          <h2>Frequently asked questions about AI paper search and review</h2>
          <h3>What kind of AI paper search tool is Jiphyeonjeon?</h3>
          <p>It connects multiple scholarly search paths in one place, then carries a question from paper discovery through comparison, deep review, source verification, and follow-up reading.</p>
          <h3>How are claims in an AI paper review verified?</h3>
          <p>Jiphyeonjeon locates the source passages behind important claims and labels them as direct quotation, paraphrase, inference, or unverified.</p>
          <h3>What can I use without signing in?</h3>
          <p>You can search papers and read public reviews immediately. Sign in only when you want to save reviews, notes, and bookmarks in your personal research workspace.</p>
        </section>
        <section id="claude">
          <h2>Use Jiphyeonjeon with Claude</h2>
          <p>The product overview and public paper reviews are readable on the web. Jiphyeonjeon Agent is an optional open-source extension installed separately from the web service, bringing paper search, review, bookmarks, and curriculum tools into Claude conversations.</p>
          <p><a href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent">View installation instructions and source</a></p>
        </section>
        <nav aria-label="Main pages">
          <a href="/">Paper search</a> · <a href="/blog">Research blog</a> · <a href="/blog/category/paper-review">Public paper reviews</a>
        </nav>
        <footer>
          <span>© Jiphyeonjeon</span>
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
