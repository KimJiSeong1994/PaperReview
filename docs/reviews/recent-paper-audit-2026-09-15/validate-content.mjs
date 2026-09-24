// Run from repository root: node docs/reviews/recent-paper-audit-2026-09-15/validate-content.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const audit = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(audit, '../../..');
const require = createRequire(path.join(repo, 'web-ui/package.json'));
const { unified } = await import(require.resolve('unified'));
const { default: remarkParse } = await import(require.resolve('remark-parse'));
const { default: remarkMath } = await import(require.resolve('remark-math'));
const { default: remarkGfm } = await import(require.resolve('remark-gfm'));
const katex = require('katex');
const read = name => JSON.parse(fs.readFileSync(name, 'utf8'));
const slugs = read(path.join(audit, 'scope.json')).slugs;
const current = read(path.join(repo, 'data/blog/posts.json')).posts;
const baseline = read(path.join(audit, 'baseline-posts.json')).posts;
const parser = unified().use(remarkParse).use(remarkMath).use(remarkGfm);
const visit = (node, fn) => { fn(node); for (const child of node.children ?? []) visit(child, fn); };
const images = body => {
  const result = [];
  visit(parser.parse(body), node => { if (node.type === 'image') result.push(node.url); });
  return result;
};
assert.equal(new Set(current.map(p => p.slug)).size, current.length, 'Duplicate slug');
assert.equal(new Set(current.map(p => p.id)).size, current.length, 'Duplicate id');
let untouched = 0;
for (const old of baseline) {
  if (slugs.includes(old.slug)) continue;
  assert.deepEqual(current.find(p => p.slug === old.slug), old, `Unrelated post changed: ${old.slug}`);
  untouched++;
}
const results = [];
for (const slug of slugs) {
  const dir = path.join(audit, 'articles', slug);
  const original = read(path.join(dir, 'original.json'));
  const post = current.find(p => p.slug === slug);
  assert.ok(post, slug);
  assert.equal(post.content, fs.readFileSync(path.join(dir, 'revised.md'), 'utf8'), slug);
  assert.equal(post.content, read(path.join(dir, 'post.json')).content, slug);
  assert.notEqual(post.content, original.content, `No revision: ${slug}`);
  for (const key of ['id', 'slug', 'title', 'created_at', 'published', 'category', 'tags', 'thumbnail_url', 'author']) {
    assert.deepEqual(post[key], original[key], `${slug}: metadata ${key}`);
  }
  assert.ok(post.excerpt.length > 0 && post.reading_time_min > 0);
  assert.ok(post.content.includes('## References'));
  assert.ok(!/리뷰어 추가 비판|\bTODO\b|\bTBD\b|이 글에서 구분하는 세 층위/.test(post.content), slug);
  assert.ok(!/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(post.content), slug);
  const beforeImages = images(original.content);
  const afterImages = images(post.content);
  assert.deepEqual(afterImages, beforeImages, `${slug}: image order/URLs`);
  for (const url of [...afterImages, post.thumbnail_url]) {
    if (!url?.startsWith('/api/blog/figures/')) continue;
    assert.ok(fs.existsSync(path.join(repo, 'data/blog/figures', url.split('/').at(-1))), url);
  }
  let equations = 0;
  visit(parser.parse(post.content), node => {
    if (!['math', 'inlineMath'].includes(node.type)) return;
    katex.renderToString(node.value, { displayMode: node.type === 'math', throwOnError: true, strict: 'error' });
    equations++;
  });
  const headings = [...post.content.matchAll(/^## (\d+)\./gm)].map(m => Number(m[1]));
  assert.deepEqual(headings, headings.map((_, i) => i + 1), `${slug}: section sequence`);
  results.push({ slug, equations, figures: afterImages.length, metadata_preserved: true, artifact_matches: true });
}
const result = { status: 'pass', posts: results, unchanged_posts: untouched, total_posts: current.length };
fs.writeFileSync(path.join(audit, 'content-validation.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
