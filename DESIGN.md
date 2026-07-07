# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-07-08
- Primary product surfaces: Blog index, blog category hubs, blog post detail pages, paper-review articles.
- Evidence reviewed:
  - `web-ui/src/components/BlogPage.tsx` — blog detail structure, markdown renderer, metadata/tags.
  - `web-ui/src/components/BlogPage.css` — dark-first tokens, blog cards, detail typography.
  - `docs/design-bookmark-review-highlight-integration.md` — existing repo design-document style and product context.
  - Live/production target: `https://jiphyeonjeon.kr/blog/category/paper-review` and SkillOpt paper-review post.

## Brand
- Personality: research-grade, calm, technical, trustworthy, and text-forward.
- Trust signals: clear metadata, stable reading rhythm, strong section hierarchy, legible figures/tables, restrained accent color.
- Avoid: glossy marketing panels, noisy gradients, cramped academic tables, excessive borders, low-contrast dark text.

## Product goals
- Goals:
  - Make long Korean/English mixed paper-review posts readable for deep study.
  - Preserve full markdown fidelity: tables, code, math, figures, blockquotes, references.
  - Keep the blog consistent with the existing dark-first Jiphyeonjeon visual language.
- Non-goals:
  - Do not create a new component system or replace ReactMarkdown.
  - Do not turn blog posts into magazine layouts that reduce technical density.
- Success signals:
  - Long paper reviews can be scanned by section and read linearly without fatigue.
  - Wide tables and figures do not break mobile or desktop layouts.
  - Paper-review category pages and detail pages remain fast and accessible.

## Personas and jobs
- Primary personas: researchers, engineers, and the site owner reviewing literature notes.
- User jobs:
  - Open a paper-review post and quickly understand its thesis and structure.
  - Read dense sections, tables, and references without copy/paste cleanup.
  - Revisit figures and method summaries as study material.
- Key contexts of use: desktop deep reading, mobile skim, dark-mode default, Korean/English mixed content.

## Information architecture
- Primary navigation: blog index defaults to Engineering; Paper Reviews live under `/blog/category/paper-review`.
- Core routes/screens: `/blog`, `/blog/category/:category`, `/blog/:slug`.
- Content hierarchy: category badge/tags → title → author/date/read time → markdown article → admin controls.

## Design principles
- Principle 1: Reading rhythm over decoration — line length, spacing, and hierarchy carry the design.
- Principle 2: Technical artifacts are first-class — tables, code, math, and figures must have dedicated visual treatment.
- Tradeoffs: Favor dense but readable academic presentation over large hero imagery or marketing-style whitespace.

## Visual language
- Color: dark-first neutral background with indigo for paper-review accents and teal for engineering accents.
- Typography: inherit app font for prose; monospace only for code; mixed Korean/English line-height ≥ 1.85.
- Spacing/layout rhythm: 760–860px article measure, generous heading margins, block-level separation for figures/tables.
- Shape/radius/elevation: subtle 14–20px rounded surfaces, 1px translucent borders, no heavy shadows.
- Motion: minimal hover/focus transitions only.
- Imagery/iconography: figures appear as framed research artifacts with neutral backing.

## Components
- Existing components to reuse: `BlogPage`, `CategoryBadge`, `blog-tag`, theme tokens in `BlogPage.css`.
- New/changed components: CSS-only improvements for blog detail hero, markdown prose, tables, images, blockquotes, code.
- Variants and states: dark and light theme via existing CSS variables; responsive mobile table overflow.
- Token/component ownership: `BlogPage.css` owns blog-specific article tokens and styles.

## Accessibility
- Target standard: WCAG AA practical readability.
- Keyboard/focus behavior: preserve existing focus-visible styles and link focus outlines.
- Contrast/readability: body text uses `--text-soft`, headings `--text-strong`, muted metadata only for secondary information.
- Screen-reader semantics: preserve semantic markdown headings, tables, links, and article role.
- Reduced motion and sensory considerations: no new animation; hover transitions remain short and nonessential.

## Responsive behavior
- Supported breakpoints/devices: mobile width ≥ 360px through desktop.
- Layout adaptations: desktop article width narrows for prose; tables scroll horizontally; title scales with `clamp()`.
- Touch/hover differences: hover affordances are supplemental, not required.

## Interaction states
- Loading: existing skeletons remain.
- Empty: existing blog empty state remains.
- Error: existing blog error banner remains.
- Success: published post visible in category and detail route.
- Disabled: existing editor disabled state remains.
- Offline/slow network, if applicable: no new offline behavior.

## Content voice
- Tone: precise, analytical, evidence-aware.
- Terminology: use “paper review”, “References”, “figure”, “method”, and domain terms consistently.
- Microcopy rules: keep metadata concise; avoid redundant labels around obvious article content.

## Implementation constraints
- Framework/styling system: React + ReactMarkdown + plain CSS in `web-ui/src/components/BlogPage.css`.
- Design-token constraints: extend existing CSS variables; do not introduce Tailwind or a new token package.
- Performance constraints: CSS-only detail improvements; no extra client runtime.
- Compatibility constraints: preserve dark default and light override behavior.
- Test/screenshot expectations: run `pytest -q tests/test_seo.py`, `npm --prefix web-ui run build`, and live HTML checks for article, figures, and references.

## Open questions
- [ ] Whether to add a generated table of contents for long reviews / owner: product / impact: navigation in 10k+ word posts.
- [ ] Whether to show paper metadata as a dedicated summary card instead of markdown body / owner: product / impact: consistency across future paper reviews.
