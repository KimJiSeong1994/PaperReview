# Recent paper reviews: easy reading first

The existing canonical posts now open with their reviewed Korean easy-reading
articles. `?view=deep` selects the detailed article through the established
reading control beside the PDF action.

| Slug | Default reading | Detailed reading | Source version |
| --- | --- | --- | --- |
| `rlt` | 7 min | 13 min | Technical report revised September 17, 2026 |
| `rsi-roadmap` | 7 min | 46 min | arXiv:2609.11873v1 |
| `ttpo` | 7 min | 30 min | arXiv:2608.27448v1 |
| `incoder-32b-thinking` | 7 min | 33 min | arXiv:2604.03144v1 |
| `codenib` | 8 min | 43 min | arXiv:2607.25431v1 |

## Content provenance

The five manuscripts and excerpts passed separate drafting, skeptical review,
primary-source fact verification, Korean humanization, and post-edit semantic
verification. PaperWiki-reviewed copies are the publishing source. Citation
headers use the existing quoted-title format for consistent PDF and SEO metadata.

Four detailed articles retain their previously published bytes. RLT's detailed
article was separately rewritten and independently checked against the 41-page
September 17 revision, which adds algorithmic experiments and two coauthors.
Its September 12 PaperWiki manuscript is preserved as
`rlt-deep-review-2026-09-12.md`. The old diagram is no longer used as the revised
article's thumbnail.

RLT primary PDF SHA-256:
`c4a2c6f78a2b17c25d62747d5f67ed643da7426760d57f0534fcba2fbf6ce6ab`.

The review distinguishes the main eight-layer, three-seed study from the separate
sixteen-layer, single-seed appendix. It does not claim measured hardware, RL, or
RLT-2 performance.

Post IDs, canonical URLs, titles, publication dates, categories, and tags are
preserved. The other 83 posts are unchanged.

## Direct PDF support

An explicit HTTPS `[PDF](...pdf)` citation supplies a direct PDF when there is no
arXiv identifier. arXiv and DOI identity priorities remain unchanged. Server and
client extraction agree. The RLT PDF proxy exception applies only to
`yifanzhang-pro.github.io`; descendant, unrelated GitHub Pages, and lookalike
hosts do not inherit access. Existing private-address and redirect checks remain.

## Validation

- Relevant blog, SEO, PDF-proxy and hardening tests: 130 passed.
- Frontend citation, reading-view and structured-data tests: 51 passed.
- Exact-host follow-up: 9 proxy/hardening tests passed; independent code review approved.
- TypeScript/Vite production build, changed Python lint, and diff checks passed.
- Preview API/SSR: five posts, ten reading views, stable canonical identity,
  matching excerpts, RSS and sitemap passed.
- Browser: twenty desktop/light and mobile/dark reading states, keyboard
  switching, reload, history and no-JavaScript navigation passed.
- RLT's actual official PDF passed through the proxy and rendered as 41 pages.
