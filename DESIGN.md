# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-08-01
- Primary product surfaces: public home/search, introduction page, blog/category/series pages, paper-review articles, authenticated research workspace.
- Evidence reviewed:
  - `web-ui/src/App.tsx`, `web-ui/src/App.css`, `web-ui/src/index.css` — application shell, navigation, theme tokens, and hanok visual language.
  - `web-ui/src/components/IntroducePage.tsx`, `LandingSections.tsx` and their CSS — introduction narrative, conversion paths, responsive behavior.
  - `web-ui/src/components/SearchPage.tsx`, `MyPage.tsx`, `PaperViewerRoute.tsx` — implemented research flows and interaction states.
  - `data/blog/posts.json` — public result inventory and introduction-page proof count.
  - `docs/design-bookmark-review-highlight-integration.md`, `docs/mcp-distribution.md` — product boundaries and distribution context.
  - `web-ui/public/introduce-hanok-*.{png,webp}`, `Jiphyeonjeon_llama.*` — brand assets.
  - `KimJiSeong1994/jiphyeonjeon-agent` main branch, reviewed 2026-08-01 — Claude integration claims, 11 MCP tools, and 6 user workflow skills.
  - Official Elicit, Consensus, SciSpace, ResearchRabbit, Litmaps, Connected Papers, Semantic Scholar, and Undermind product pages, reviewed 2026-08-01 — content-positioning evidence only, not visual references.

## Brand
- Personality: research-grade, calm, technical, trustworthy, Korean-first, and text-forward.
- Trust signals: verifiable public outputs, precise scope language, clear metadata, visible source paths, restrained visual hierarchy.
- Avoid: glossy SaaS marketing panels, invented performance numbers, noisy gradients, excessive borders, low-contrast text, and feature-count theater.

## Product goals
- Goals:
  - Explain Jiphyeonjeon as the research workflow after paper discovery: search, review, evidence checking, and next-reading paths.
  - Let new visitors judge quality from public artifacts before requiring sign-in or installation.
  - Route visitors by intent: search now, read public reviews, or connect Claude for repeated workflows.
  - Keep long Korean/English mixed research content readable for deep study.
- Non-goals:
  - Do not promise fixed review completion times without persisted measurements.
  - Do not imply every capability is available without authentication or that every configured source always responds.
  - Do not use volatile public-review inventory counts as a trust metric; link to the live public library instead.
  - Do not introduce a new component library or design-system dependency.
- Success signals:
  - A first-time visitor can state what Jiphyeonjeon does and why it differs from a paper search engine after the hero and proof block.
  - Every numeric or capability claim has a repository or external-manifest source.
  - Primary actions remain reachable and understandable at 360px and desktop widths.
  - Long paper reviews remain scannable and technically faithful.

## Personas and jobs
- Primary personas: researchers, graduate students, research engineers, and technical readers building a literature map.
- User jobs:
  - Find relevant papers across currently configured sources without manually merging duplicates.
  - Review selected papers, inspect the evidence behind generated claims, and decide what to read next.
  - Learn a new topic in a defensible order and preserve outputs as reviews, notes, or curricula.
  - Reuse the same workflow from Claude through MCP and skills.
- Key contexts of use: desktop deep research, mobile evaluation/skimming, dark-mode default, Korean/English mixed content.

## Information architecture
- Primary navigation: Home/search, 소개, Blog, My Page; admin tools appear only for authorized users.
- Core routes/screens: `/`, `/introduce`, `/blog`, `/blog/category/:category`, `/blog/series/:seriesId`, `/blog/:slug`, `/mypage`, `/paper-viewer`.
- `/introduce/` is the canonical public product explanation. Its build artifact must keep
  meaningful Korean fallback content, crawlable internal links, and route-specific
  `AboutPage` JSON-LD so search and answer engines do not depend on client rendering.
- Introduction hierarchy: product definition → access and scope → differentiators → four-stage workflow → visible claim/evidence example and public outputs → capability detail → optional Claude extension → final actions.
- Blog hierarchy: category/series context → title and metadata → markdown article → related navigation/admin controls.

## Design principles
- Evidence before breadth: prove value with public outputs and source-aware language before listing capabilities.
- One research story: describe discovery, review, verification, and learning as one continuous flow instead of disconnected features.
- Reading rhythm over decoration: typography, spacing, and a few meaningful visual anchors carry the design.
- Progressive disclosure: keep MCP tool catalogs and installation detail available without making them the first-time visitor's main path.
- Tradeoffs: favor an editorial research dossier over a dense dashboard or conventional card-heavy landing page.

## Visual language
- Color: dark-first neutral background; indigo for actions and research-review accents; warm amber is limited to dark-theme hanok lighting while the light-theme illustration stays neutral.
- Typography: Pretendard/app stack for prose; monospace only for commands and tool names; mixed Korean/English line-height at least 1.75.
- Spacing/layout rhythm: 900–1120px intro canvas, 64–104px section rhythm on desktop, 40–64px on mobile, prose measure near 68ch.
- Shape/radius/elevation: 10–18px restrained surfaces, 1px translucent borders, quiet shadows; use open editorial rows before cards.
- Motion: short nonessential hover/focus transitions; honor reduced-motion preferences.
- Imagery/iconography: hanok/llama assets establish the brand; product diagrams and published artifacts establish trust. Decorative imagery must not obscure text.

## Components
- Existing components to reuse: `SEOHead`, shared app header/footer, `LandingSections`, `CopySnippet`, `Link`, existing theme tokens and hanok assets.
- New/changed components: intro hero scope strip, local section navigation, evidence-led differentiator rows, visible claim/evidence example, public-output links, intent-split closing CTA.
- Variants and states: dark/light themes, desktop/mobile workflow layout, collapsed/expanded MCP details, copy success feedback.
- Token/component ownership: global tokens remain in `index.css`; intro-specific layout and variants stay in `IntroducePage.css` and `LandingSections.css`; blog article styling remains in `BlogPage.css`.

## Accessibility
- Target standard: WCAG 2.2 AA practical compliance.
- Keyboard/focus behavior: every CTA, anchor, summary, and copy control has a visible focus ring; in-page anchors account for the fixed header.
- Contrast/readability: primary text uses strong tokens; muted text is secondary only; light-theme borders and buttons retain visible contrast.
- Screen-reader semantics: one page `h1`, ordered heading levels, semantic sections/lists/tables, descriptive link labels, decorative art hidden from assistive technology.
- Reduced motion and sensory considerations: no required animation; transitions are disabled or minimized under `prefers-reduced-motion`.

## Responsive behavior
- Supported breakpoints/devices: 360px mobile through wide desktop; primary breakpoint 640px and layout breakpoint 900px.
- Layout adaptations: two-column hero becomes linear; proof metrics wrap; workflow rail becomes stacked; wide tool tables scroll; CTAs become comfortable touch targets.
- Touch/hover differences: hover is supplemental; all mobile interactive targets are at least 44px high.

## Interaction states
- Loading: lazy routes show the existing app loading state; copy buttons retain layout while feedback changes.
- Empty: search and blog empty states remain explicit and actionable.
- Error: failed search/review/API states preserve the user's query or task context.
- Success: copied commands announce success; completed review/public links expose the resulting artifact.
- Disabled: long-running research actions communicate unavailable/waiting state instead of silently ignoring input.
- Offline/slow network, if applicable: introduction content and navigation remain useful without backend data; no timing promise is shown.

## Content voice
- Tone: precise, analytical, calm, evidence-aware, and Korean-first.
- Terminology: use “논문 검색”, “딥리뷰”, “원문 근거”, “사실검증”, “학습 경로”, and “공개 리뷰” consistently; keep MCP/tool identifiers in English.
- Microcopy rules: lead with one concrete research outcome before listing features; describe the connected path from question to evidence and next reading; qualify runtime-dependent claims with “최대” or “구성된”; refer to the public-review library without a volatile item count; state which actions need sign-in or a separate extension; avoid fixed speed claims, unsupported superiority claims, and absolutes; do not conflate fast review with deep fact verification.

## Implementation constraints
- Framework/styling system: React 19 + TypeScript + React Router + plain CSS.
- Design-token constraints: extend existing CSS variables; do not introduce Tailwind, a new token package, or a new runtime dependency.
- Performance constraints: reuse optimized WebP/PNG assets, lazy-load the intro route, and avoid new client data fetching solely for decoration.
- Compatibility constraints: preserve dark default, light overrides, production routing, canonical metadata, and static crawler discovery.
- Test/screenshot expectations: targeted intro/SEO tests, full frontend tests, production build, `git diff --check`, and desktop/mobile dark/light screenshots.

## Open questions
- [ ] Add measured review-duration telemetry before publishing latency ranges / owner: product + backend / impact: performance proof.
- [ ] Decide whether a real product screenshot should replace the code-native workflow preview once stable screenshot fixtures exist / owner: design / impact: stronger artifact proof.
- [ ] Whether to add a generated table of contents for 10k+ word reviews / owner: product / impact: long-form navigation.
