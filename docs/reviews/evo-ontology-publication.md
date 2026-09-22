# EvoOntology publication

One new paper-review post opens with the Korean easy article at `/blog/evo-ontology`; `/blog/evo-ontology?view=deep` selects the detailed review while retaining the base canonical URL. Both manuscripts were reviewed and saved in PaperWiki before promotion.

## Evidence and editorial decisions

- Primary: Chong, Zhang, Fan & Du (2026), *EvoOntology: A Self-Evolving Ontology Layer for Data Agents*, arXiv:2609.15779v1, 14 September 2026, 11 pages. [Primary PDF](https://arxiv.org/pdf/2609.15779v1).
- Four core figures in easy reading and all eight in detailed reading; every figure opens at original size. Source PDF/crop/image hashes are in `evo-ontology-figure-provenance.json`.
- Separate source and skeptical reviews verified metrics, denominators, the reciprocal 70/30 protocol, gate definition and figure panels. A later semantic check verified the actual im-not-ai edits preserved those claims.
- The 20% reduction describes per-task token usage on the four-backbone DDR subset, not total monetary/runtime or ontology-building cost. Identical rounded table rows do not establish an error; plotted plateaus do not establish a gate violation. Transfer comparisons hold the deployment backbone fixed.
- The original substantive method, ablation and transfer analysis is retained. Captions are shorter, and references cite the primary work rather than copying its secondary bibliography. Numeric tilde ranges use en dashes to avoid Markdown strikethrough.
- Humanization was conservative (1.2% easy / 0.6% detailed). Its self-report remains C, 5/6, because protected/source-style comma patterns were retained; facts and citations take priority over a stylistic quota. No experiment was independently reproduced.

## Validation

103 related tests passed (68 backend, 35 frontend), along with TypeScript/Vite build and diff checks. Preview API/SSR, excerpts, canonical citation identity, RSS and sitemap passed. Desktop/light and mobile/dark checks decoded all 24 easy/deep image instances, verified ten detailed TOC anchors, reading-time/mode changes, PDF identity, reload/back and no-JavaScript navigation. All 88 existing posts remain byte-equivalent as records; only one new post and its eight source images are added.
