# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-08-14
- Primary product surfaces: public home/search, introduction page, blog/category/series pages, paper-review articles, authenticated research workspace, academic poster generation and preview/export.
- Evidence reviewed:
  - `web-ui/src/App.tsx`, `web-ui/src/App.css`, `web-ui/src/index.css` — application shell, navigation, theme tokens, and hanok visual language.
  - `web-ui/src/components/IntroducePage.tsx`, `LandingSections.tsx` and their CSS — introduction narrative, conversion paths, responsive behavior.
  - `web-ui/src/components/SearchPage.tsx`, `MyPage.tsx`, `PaperViewerRoute.tsx` — implemented research flows and interaction states.
  - `data/blog/posts.json` — public result inventory and introduction-page proof count.
  - `docs/design-bookmark-review-highlight-integration.md`, `docs/mcp-distribution.md` — product boundaries and distribution context.
  - `app/DeepAgent/config/style_guides/academic_poster_general.md`, `app/DeepAgent/config/poster_styles.yaml`, `app/DeepAgent/config/style_manager.py` — academic poster generation style contract, YAML theme defaults, and generated CSS.
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
- Poster hierarchy: paper/review thesis → author/source context → primary evidence wall → metrics with real labels → method/figure/table support → limitations → provenance/review metadata → compact references. The poster is a primary generated artifact, not a decorative export of the search page.

## Design principles
- Evidence before breadth: prove value with public outputs and source-aware language before listing capabilities.
- One research story: describe discovery, review, verification, and learning as one continuous flow instead of disconnected features.
- Reading rhythm over decoration: typography, spacing, and a few meaningful visual anchors carry the design.
- Progressive disclosure: keep MCP tool catalogs and installation detail available without making them the first-time visitor's main path.
- Tradeoffs: favor an editorial research dossier over a dense dashboard or conventional card-heavy landing page.
- Poster principle: evidence density beats ornament. Academic posters use a 4:3 A3 landscape Editorial Evidence Wall that keeps thesis, evidence, metrics, limitations, and metadata visible without relying on remote assets or placeholder claims.

## Visual language
- Color: dark-first neutral background; indigo for actions and research-review accents; warm amber is limited to dark-theme hanok lighting while the light-theme illustration stays neutral.
- Typography: Pretendard/app stack for prose; monospace only for commands and tool names; mixed Korean/English line-height at least 1.75.
- Spacing/layout rhythm: 900–1120px intro canvas, 64–104px section rhythm on desktop, 40–64px on mobile, prose measure near 68ch.
- Shape/radius/elevation: 10–18px restrained surfaces, 1px translucent borders, quiet shadows; use open editorial rows before cards.
- Motion: short nonessential hover/focus transitions; honor reduced-motion preferences.
- Imagery/iconography: hanok/llama assets establish the brand; product diagrams and published artifacts establish trust. Decorative imagery must not obscure text.
- Academic poster visual contract: default generated posters use a 1600px x 1200px, 4:3 A3 landscape canvas with a 12-column grid, system-only fonts, sentence case, no forced uppercase, no negative letter spacing, and wrapping rules for long Korean/English mixed titles and technical identifiers. Poster palettes stay academic and multi-neutral rather than one-note gradients.

## Components
- Existing components to reuse: `SEOHead`, shared app header/footer, `LandingSections`, `CopySnippet`, `Link`, existing theme tokens and hanok assets.
- New/changed components: intro hero scope strip, local section navigation, evidence-led differentiator rows, visible claim/evidence example, public-output links, intent-split closing CTA.
- Search graph contract: the relationship graph remains the primary search-results workspace; related-paper and paper-detail panels are visible by default and independently collapsible. View settings are open by default but remain collapsible, and controls stay clear of task-critical graph content.
- Graph semantics: distinguish the origin paper, current selection, path nodes, and topic communities without relying on color alone; expose the active edge-calculation method and keep year as tooltip or secondary metadata rather than the primary node color.
- Graph visual treatment: use a `Research Nexus Console` workspace in dark mode: a deep neutral canvas, six restrained community colors, citation-and-connectivity-aware hub sizing, and softly bounded topic regions. Show the full edge set by default at restrained opacity, while reserving layered glow and sampled curves for selected-neighborhood and strongest-path relationships; keep a visible control for switching back to the quieter structural backbone. Light mode removes ambient glow and uses calmer, higher-luminance community colors.
- Graph exploration layers: keep `기본 지형` as the permanent ranked-field canvas, with independently switchable `3-hop` and `원문 경로` overlays. Both may be active together, preserve the selected paper and node positions, and avoid implying citation direction; hop numbers mean strongest-neighbor expansion depth, not citation depth. Compute community positioning against the full fetched graph before applying 20/35/50 visibility limits so the user's mental map does not shift with density controls.
- Graph communities and evidence: keep softly bounded topic communities visible as stable spatial context; expose similarity score and shared title/keyword terms on focused relationships so every emphasized edge has an inspectable reason.
- Research-landscape decluttering: preserve the organic source layout, gently expand community centroids, and slightly compact each community instead of packing topics into isolated grid zones. The research landscape remains the single stable canvas; 3-hop and origin-path analysis are additive layers on that canvas. Use tight low-alpha hulls that remain visibly bounded against the canvas, render default full edges quietly, and retain the structural-backbone toggle as the decluttered alternative.
- Graph density: use all 50 search candidates by default with explicit 20/35/50 controls so the relationship surface does not discard already-fetched papers. In `3-hop 주변`, retain every reachable layer up to the chosen limit and expose 1-hop, 2-hop, and 3-hop distance through rings, counts, and text. Always retain task-critical nodes such as the origin, current selection, and active path; keep any hidden results available in the synchronized paper list.
- Graph workspace chrome: the graph expands when either side panel is collapsed. Keep the paper explorer compact, open both the related-paper and paper-detail panels by default, and place settings, labels, and edge-density controls in an accessible floating tool stack that does not cover important graph content.
- Admin analytics trust contract: distinguish verified crawler identity, successful indexable-content fetches, content failures, discovery 404s, and suspected security scans. Danger styling is reserved for verified content failures; unverified identities and expected probes use neutral status treatments, and every selected period discloses the actual nginx log coverage.
- Variants and states: dark/light themes, desktop/mobile workflow layout, collapsed/expanded MCP details, copy success feedback.
- Token/component ownership: global tokens remain in `index.css`; intro-specific layout and variants stay in `IntroducePage.css` and `LandingSections.css`; blog article styling remains in `BlogPage.css`.
- Poster components: reuse the generated HTML preview/download modal, sanitized poster iframe flow, YAML theme tokens, and `StyleManager` CSS output. New poster sections should map to thesis, evidence, metrics, figure/table, limitations, metadata, and references rather than generic card grids.
- Poster evidence contract: metric blocks must use actual labels and source context; thesis/evidence metadata must identify generation date/status and safe provenance; limitations must remain visible as scholarly content.

## Accessibility
- Target standard: WCAG 2.2 AA practical compliance.
- Keyboard/focus behavior: every CTA, anchor, summary, and copy control has a visible focus ring; in-page anchors account for the fixed header.
- Contrast/readability: primary text uses strong tokens; muted text is secondary only; light-theme borders and buttons retain visible contrast.
- Screen-reader semantics: one page `h1`, ordered heading levels, semantic sections/lists/tables, descriptive link labels, decorative art hidden from assistive technology.
- Graph accessibility: synchronize graph selection with a keyboard-operable paper list and announce the selected paper's direct relationship count; graph filters and mobile panel controls meet the same visible-focus and touch-target rules as primary actions.
- Graph layer accessibility: implement analysis layers as an ARIA-labelled pressed-button group with checkbox-like state indicators, disable selection-dependent layers until a paper is selected, and summarize active hop/path evidence as text outside the canvas. Preserve an off-screen layer/count summary when compact layouts hide visible detail text.
- Graph sensory accessibility: community color is always paired with role shape, focus ring, text label, or paper-list marker. On desktop, show at least one readable representative-paper label per visible community before filling the remaining label budget, with at most eight priority labels total. Keep community annotations on one natural line with their `·` separator intact; do not force semantic phrases onto separate lines. Keep canvas labels out of compact mobile layouts, preserve the off-canvas selection summary, maintain a calm non-glowing light theme, and meet 44px touch targets on mobile.
- Reduced motion and sensory considerations: no required animation; transitions are disabled or minimized under `prefers-reduced-motion`.
- Poster accessibility: generated posters target WCAG 2.2 AA for preview/export, one `h1`, semantic section headings, selectable text, real metric labels, non-color-only evidence encoding, visible focus for modal controls, and static content under reduced motion.

## Responsive behavior
- Supported breakpoints/devices: 360px mobile through wide desktop; primary breakpoint 640px and layout breakpoint 900px.
- Layout adaptations: two-column hero becomes linear; proof metrics wrap; workflow rail becomes stacked; wide tool tables scroll; CTAs become comfortable touch targets.
- Search graph adaptation: at 900px and below the graph is rendered first at full width; the default-open related-paper and paper-detail panels stack below it and remain independently collapsible instead of forcing the three-column desktop canvas off-screen. At 520px and below, graph tools occupy a dedicated horizontal row above the canvas rather than overlaying nodes or community regions.
- Touch/hover differences: hover is supplemental; all mobile interactive targets are at least 44px high.
- Poster responsive contract: 1200-1600px previews retain the 4:3 12-column canvas; 760-1199px previews preserve source order with reduced spans; below 760px the poster stacks as a readable article preview without clipped titles or horizontal overflow. Print output centers the 4:3 canvas at 396mm × 297mm on a marginless 420mm × 297mm A3 landscape page, preserving ratio with narrow side gutters, exact color adjustment, and no external font/network dependency.

## Interaction states
- Loading: paper search uses the Jiphyeonjeon library scene as a narrative status surface: the canonical scholar hero is visually prominent through its round silhouette, expressive face, and `RESEARCH` headband while visibly finding books; concise Korean copy explains that titles and core content are being reviewed. Dark mode uses the warm lamplit ink scene; light mode switches to a separate neutral hanji-white and muted-indigo daylight asset rather than filtering the dark artwork or carrying its ochre cast across themes. Keep the status truthful (no invented percentage or time promise), expose it through a polite live region, treat the illustration as decorative, and limit motion to a subtle nonessential pulse/zoom that is removed under reduced-motion. Lazy routes keep the compact app loading state; copy buttons retain layout while feedback changes.
- Empty: search and blog empty states remain explicit and actionable.
- Error: failed search/review/API states preserve the user's query or task context.
- Success: copied commands announce success; completed review/public links expose the resulting artifact.
- Disabled: long-running research actions communicate unavailable/waiting state instead of silently ignoring input.
- Offline/slow network, if applicable: introduction content and navigation remain useful without backend data; no timing promise is shown.

## Content voice
- Tone: precise, analytical, calm, evidence-aware, and Korean-first.
- Terminology: use “논문 검색”, “딥리뷰”, “원문 근거”, “사실검증”, “학습 경로”, and “공개 리뷰” consistently; keep MCP/tool identifiers in English.
- Microcopy rules: lead with one concrete research outcome before listing features; describe the connected path from question to evidence and next reading; qualify runtime-dependent claims with “최대” or “구성된”; refer to the public-review library without a volatile item count; state which actions need sign-in or a separate extension; avoid fixed speed claims, unsupported superiority claims, and absolutes; do not conflate fast review with deep fact verification.
- Graph microcopy: call the surface “논문 관계 그래프”; name the actual relationship method (for example “제목·키워드 유사도”), label neighborhood depth as `1-hop / 2-hop / 3-hop 강한 관계 확장`, and avoid implying citation, causal, or directional relationships when the graph is undirected similarity data.
- Graph layer microcopy: use “기본 지형”, “3-hop”, and “원문 경로”, with a visible `기본 지형 + …` active-layer summary; reserve “선행 연구”, “후속 연구”, and directional arrows for future citation data that actually supports those claims. Keep the console status Korean-first and omit implementation details such as layout algorithms.

## Implementation constraints
- Framework/styling system: React 19 + TypeScript + React Router + plain CSS.
- Design-token constraints: extend existing CSS variables; do not introduce Tailwind, a new token package, or a new runtime dependency.
- Performance constraints: reuse optimized WebP/PNG assets, lazy-load the intro route, and avoid new client data fetching solely for decoration.
- Compatibility constraints: preserve dark default, light overrides, production routing, canonical metadata, and static crawler discovery.
- Test/screenshot expectations: targeted intro/SEO tests, full frontend tests, production build, `git diff --check`, and desktop/mobile dark/light screenshots.
- Poster implementation constraints: default poster styling lives in `poster_styles.yaml` and generated CSS from `style_manager.py`; keep the 4:3 canvas, 1200-1600px flexible width, self-contained system font stack, print CSS, responsive CSS, and legacy `.grid-container` / `.col` compatibility. Do not add new runtime dependencies or remote font/image requirements.

## Open questions
- [ ] Add measured review-duration telemetry before publishing latency ranges / owner: product + backend / impact: performance proof.
- [ ] Decide whether a real product screenshot should replace the code-native workflow preview once stable screenshot fixtures exist / owner: design / impact: stronger artifact proof.
- [ ] Whether to add a generated table of contents for 10k+ word reviews / owner: product / impact: long-form navigation.
