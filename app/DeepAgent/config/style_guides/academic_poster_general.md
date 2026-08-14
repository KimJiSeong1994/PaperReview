# Academic Poster Style Guide (General)

## Output Contract

- Default format: A3 landscape academic poster with a 4:3 composition.
- Screen canvas: design and preview against 1600px x 1200px; allow responsive rendering from 1200px to 1600px without changing the information hierarchy.
- Poster surface: one self-contained HTML document. Do not depend on remote fonts, CDN stylesheets, external scripts, tracking pixels, or network-loaded decorative assets.
- Primary model: Editorial Evidence Wall, not a slide deck, SaaS dashboard, or decorative infographic.
- Required content: title, authors or source context when available, thesis statement, evidence blocks, metric labels, limitations, and provenance or review metadata.

## Editorial Evidence Wall

- Treat the poster as a dense but readable research wall: thesis first, evidence next, interpretation last.
- Use a 12-column grid for the main canvas. Recommended spans:
  - Title/header: 12 columns.
  - Thesis or key claim: 5-7 columns.
  - Primary figure, method map, or result table: 5-7 columns.
  - Evidence cards: 3-4 columns each.
  - Limitations, metadata, and references: 3-6 columns.
- Legacy 1-column, 2-column, and 3-column renderers may map onto the 12-column grid, but the 4:3 canvas and evidence-first hierarchy remain mandatory.
- Avoid nested cards and excessive panel chrome. Use section rhythm, rules, and restrained background shifts before adding framed containers.

## Layout And Grid

- Aspect ratio: 4 / 3.
- Default width: 1600px; responsive minimum: 1200px for poster preview and export.
- Main grid: `repeat(12, minmax(0, 1fr))`.
- Outer padding: 48px desktop/export, 32px for narrower previews, 18-24px below 760px.
- Grid gap: 24px desktop/export, 18px below 1200px, 14px below 760px.
- Header height should stay compact enough to leave evidence visible in the first viewport.
- Do not fill every pixel. Keep at least one clear reading path from thesis to evidence to implication.

## Typography

### Font Stack

Use only local/system fonts:

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", Arial, sans-serif;
```

### Hierarchy

| Element | Size | Weight | Case |
| --- | --- | --- | --- |
| Poster title | 2.4-3.1rem | 800-900 | Sentence case or source title case |
| Subtitle / thesis | 1.35-1.7rem | 600-700 | Sentence case |
| Section header | 1.05-1.25rem | 700-800 | Sentence case |
| Body text | 0.92-1.05rem | 400-500 | Sentence case |
| Metric value | 1.55-2.4rem | 800-900 | As reported |
| Labels/captions | 0.72-0.9rem | 500-650 | Sentence case |
| SVG labels | 12-16px | 500-700 | Sentence case |

### Long Titles And Mixed Language

- Do not force uppercase, negative letter spacing, or tight line-height on Korean/English mixed titles.
- Allow long titles to wrap across 2-4 lines; preserve technical terms, model names, dataset names, and equations.
- Use `overflow-wrap: anywhere` for title, section, metric, and label containers so long English identifiers do not break the poster.
- Use line-height 1.12-1.22 for titles and 1.5-1.7 for body text.

## Color Strategy

- Use a restrained academic palette with one primary color, one accent, one success/positive color, one warning/contrast color, and neutrals.
- Recommended default: primary #1d4ed8, secondary #172033, accent #d97706, success #0f766e, warning #b45309, background #f7f8fb.
- Text on colored backgrounds must meet WCAG AA contrast; prefer dark text on light evidence panels.
- Do not use pure black for body text; use deep neutral ink such as #172033 or #243044.
- Use color to connect thesis, evidence, and metric families. Do not rely on color alone for meaning.

## Evidence And Metrics

- Every metric must have a real label: dataset, unit, comparison baseline, sample size, or measurement context where available.
- Avoid placeholder labels such as "Result 1", "Metric A", "High", or "Improved" unless the source report actually uses them.
- Each evidence block should expose at least one of: source section, paper title, DOI/arXiv identifier, table/figure reference, quote context, or review provenance.
- Include a thesis/evidence metadata band with generation date, input paper count, review/session identifier when safe to reveal, and status such as synthesized, degraded, or partial.
- Limitations are a required scholarly component, not optional footer decoration.

## Shapes And Containers

- Main evidence sections may use 8px radius; avoid larger pill-like shapes for serious academic content.
- Use 1px borders, soft section rules, and low-opacity tints before heavy shadows.
- Recommended shadow: `0 8px 18px rgba(15, 23, 42, 0.08)` for the poster sheet only; evidence panels should stay flatter.
- Use tables, callout strips, and figure captions as academic containers. Avoid decorative badges that do not carry data.

## Diagrams, Lines, And Arrows

- SVG figures must include `viewBox` and render responsively with `width: 100%`.
- Prefer orthogonal paths for pipelines and method flow; use curved paths only where they clarify grouping or sequence.
- Label arrows with the actual transformation or evidence relationship, not generic "process" wording.
- Use `marker-end` for directional flows only when direction is semantically true.
- Diagram text follows the same mixed-language and wrapping rules as HTML text.

## Accessibility

- Target: WCAG 2.2 AA practical compliance for preview and downloadable HTML.
- Maintain visible focus states for modal, download, close, and any in-poster anchors.
- Preserve semantic heading order. One poster title should be the only `h1`.
- Do not convey metric state through color alone; pair color with label, icon, pattern, or text.
- Respect `prefers-reduced-motion`; poster content should be static by default.

## Responsive Preview

- 1200-1600px: keep the 12-column grid and 4:3 canvas.
- 760-1199px: retain evidence order while allowing 6-column spans; reduce padding and gaps.
- Below 760px: stack sections in source order, remove fixed min-width, and let the poster behave as a readable article preview.
- Text must not overlap or clip at any supported width. Prefer wrapping and smaller local type scales over horizontal overflow.

## Print And Export

- Print target: A3 landscape.
- Use `@page { size: A3 landscape; margin: 0; }`.
- Center the 4:3 canvas at `396mm × 297mm` inside the `420mm × 297mm` A3 page; the remaining 12mm gutters on each side preserve the poster ratio without cropping or extra pages.
- Avoid page-breaking inside figures, metric groups, evidence blocks, tables, and references where practical.
- Use exact color adjustment for print: `print-color-adjust: exact`.
- The printable poster must not depend on browser access to external font files or remote images.

## Content Quality Rules

- Lead with the paper or review thesis, not generic conference branding.
- Keep claims falsifiable and tied to evidence. Qualify generated or inferred statements.
- Prefer concise Korean-first phrasing while preserving English technical terms, dataset names, and paper titles.
- References and metadata may be compact, but they must remain readable and selectable.
