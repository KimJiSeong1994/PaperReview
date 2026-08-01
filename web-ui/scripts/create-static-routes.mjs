import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webUiDirectory = resolve(scriptDirectory, '..');
const sourcePath = resolve(webUiDirectory, 'dist/index.html');
const destinationPath = resolve(webUiDirectory, 'dist/introduce/index.html');

const title = '집현전 소개 | 논문을 찾고 근거까지 읽는 연구 도구';
const description =
  '집현전은 여러 소스에서 논문을 찾고 비교하며, 중요한 주장을 원문에서 확인하고 다음에 읽을 자료까지 정리하는 AI 연구 도구입니다.';
const canonical = 'https://jiphyeonjeon.kr/introduce';

const replacements = [
  [/<html lang="en">/, '<html lang="ko">'],
  [/(<meta\s+name="description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/(<link\s+rel="canonical"\s+href=")[^"]*("\s*\/?>)/, `$1${canonical}$2`],
  [/(<meta\s+property="og:title"\s+content=")[^"]*("\s*\/?>)/, `$1${title}$2`],
  [/(<meta\s+property="og:description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/(<meta\s+property="og:url"\s+content=")[^"]*("\s*\/?>)/, `$1${canonical}$2`],
  [/(<meta\s+property="og:locale"\s+content=")[^"]*("\s*\/?>)/, '$1ko_KR$2'],
  [/(<meta\s+property="og:locale:alternate"\s+content=")[^"]*("\s*\/?>)/, '$1en_US$2'],
  [/(<meta\s+name="twitter:title"\s+content=")[^"]*("\s*\/?>)/, `$1${title}$2`],
  [/(<meta\s+name="twitter:description"\s+content=")[^"]*("\s*\/?>)/, `$1${description}$2`],
  [/<title>[^<]*<\/title>/, `<title>${title}</title>`],
];

let document = await readFile(sourcePath, 'utf8');

for (const [pattern, replacement] of replacements) {
  if (!pattern.test(document)) {
    throw new Error(`Static route generation failed: expected markup was not found: ${pattern}`);
  }
  document = document.replace(pattern, replacement);
}

await mkdir(dirname(destinationPath), { recursive: true });
await writeFile(destinationPath, document, 'utf8');

console.log(`Created static SPA entry: ${destinationPath}`);
