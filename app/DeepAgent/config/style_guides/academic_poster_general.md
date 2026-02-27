# Academic Poster Style Guide (General)

## Color Strategy

### Zone-Based Color Assignment
- **Header Zone**: Primary color gradient background, white text
- **Content Zones**: White/light background with colored accents
- **Highlight Zones**: Accent color background for key findings
- **Footer Zone**: Subtle gray, secondary information

### Recommended Academic Color Palettes
- **Classic Blue**: Primary #2563eb, Secondary #1e293b, Accent #f59e0b, BG #f8fafc
- **Deep Teal**: Primary #0d9488, Secondary #1e293b, Accent #f97316, BG #f0fdfa
- **Royal Purple**: Primary #7c3aed, Secondary #1e293b, Accent #06b6d4, BG #faf5ff

### Color Usage Rules
- Maximum 3-4 primary colors plus neutrals
- Text on colored backgrounds must have contrast ratio >= 4.5:1
- Use opacity variants (0.1, 0.2) for subtle backgrounds
- Never use pure black (#000000) for body text; use #1e293b or #334155

## Shapes & Containers

### Section Boxes
- Border-radius: 12px for main containers, 8px for nested elements
- Box-shadow: `0 4px 6px rgba(0,0,0,0.05)` for subtle depth
- Border: 1px solid with 0.1 opacity of primary color
- Padding: 20-24px internal spacing

### Diagram Elements
- **Process boxes**: Rounded rectangles (rx=8, ry=8), filled with light primary
- **Data containers**: Rectangles with dashed borders for data/datasets
- **Decision points**: Diamond shapes for branching logic
- **Cylinders**: For database/storage representation

## Lines & Arrows

### Connection Types
- **Sequential flow**: Solid lines with arrowhead (`marker-end`)
- **Data flow**: Dashed lines (stroke-dasharray: 4,4)
- **Bidirectional**: Double arrowheads
- **Grouping**: Dotted lines for loose association

### Arrow Style
- Stroke-width: 2px for main flows, 1.5px for secondary
- Color: Match section primary or use #64748b (neutral)
- Use orthogonal paths (right angles) for structured diagrams
- Use curved paths (quadratic bezier) for organic/flow diagrams

## Typography

### Hierarchy
| Element | Size | Weight | Case |
|---------|------|--------|------|
| Poster Title | 3-3.5rem | 800-900 | Title Case or UPPERCASE |
| Subtitle | 1.5-1.8rem | 500 | Title Case |
| Section Header | 1.3-1.5rem | 700-800 | Title Case |
| Body Text | 1-1.1rem | 400 | Sentence case |
| Labels/Captions | 0.8-0.9rem | 500 | Sentence case |
| SVG Text | 12-14px | 500-600 | - |

### Font Stack
```css
font-family: 'Inter', 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
```

### Line Heights
- Titles: 1.1-1.2
- Body: 1.5-1.6
- Captions: 1.3-1.4

## SVG Best Practices

### ViewBox
- Always use `viewBox` attribute (e.g., `viewBox="0 0 600 400"`)
- Use `preserveAspectRatio="xMidYMid meet"` for responsive scaling
- Set width="100%" on the SVG element, let viewBox control proportions

### Definitions & Reuse
- Define gradients, markers, and filters in `<defs>` block
- Use `<use>` for repeated elements
- Define arrowhead markers: `<marker id="arrowhead" ...>`

### Text in SVG
- Use `text-anchor="middle"` for centered labels
- Use `dominant-baseline="middle"` for vertical centering
- Font-size in px (12-14px for labels, 16-18px for headers)
- Wrap long text with `<tspan>` elements

### Colors in SVG
- Use CSS variables where possible: `fill="var(--primary)"`
- Fallback: inline fill/stroke attributes
- Consistent opacity for overlapping elements

## Layout Principles

### Grid Structure
- **3-Column Grid**: `grid-template-columns: 1fr 1.2fr 1fr` (balanced)
- **Asymmetric Grid**: `grid-template-columns: 1fr 2fr 1fr` (center-heavy)
- Gap: 25-30px between columns
- Gap: 20-25px between section boxes

### Aspect Ratio
- Target: 20:9 (landscape, wide-format)
- Minimum width: 1600px
- Use `aspect-ratio: 20 / 9` in CSS

### Content Distribution
- Left column: Introduction, Background, Motivation
- Center column: Main results, Architecture diagrams, Charts
- Right column: Conclusions, Timeline, References

### White Space
- Poster padding: 30-40px
- Section internal padding: 20px
- Minimum gap between elements: 15px
- Don't fill every pixel — breathing room improves readability
