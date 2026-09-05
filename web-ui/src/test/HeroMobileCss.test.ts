import { describe, expect, it } from 'vitest';
import css from '../App.css?raw';

// jsdom does not evaluate media queries, so the phone hero cannot be asserted
// by rendering. This reads the stylesheet instead.
//
// It deliberately checks ORDER, not just presence. The first attempt at this
// change put both declarations in the @media block near the top of the file and
// measured no effect on the hero: a media query adds no specificity, so
// `.centered-search { min-height: auto }` there lost to the plain
// `.centered-search { min-height: calc(100vh - 80px) }` that comes later. Only
// the ::after rule took effect, because nothing later contests its `display`.
// A presence-only assertion passes against that broken file. This one does not.
function lastIndexOfRule(selector: string): number {
  let at = -1;
  for (let i = 0; ; ) {
    const next = css.indexOf(`\n${selector} {`, i);
    if (next === -1) break;
    at = next;
    i = next + 1;
  }
  return at;
}

describe('phone hero CSS', () => {
  it('drops the decorative pseudo-element and its min-height below 760px', () => {
    const media = css.match(/@media \(max-width: 760px\) \{[\s\S]*?\n\}/g) ?? [];
    const hero = media.find((block: string) => block.includes('.centered-search'));
    expect(hero, 'no @media (max-width: 760px) block targets .centered-search').toBeTruthy();
    expect(hero).toMatch(/\.centered-search\s*\{[^}]*min-height:\s*auto/);
    expect(hero).toMatch(/\.centered-search::after\s*\{[^}]*display:\s*none/);
  });

  it('places that block after every unconditional .centered-search rule', () => {
    const base = lastIndexOfRule('.centered-search');
    const override = css.indexOf('@media (max-width: 760px) {', css.indexOf('min-height: auto') - 2000);
    expect(base).toBeGreaterThan(-1);
    // The override must come later in source order, or the cascade discards it.
    expect(css.indexOf('min-height: auto')).toBeGreaterThan(base);
    expect(override).toBeGreaterThan(base);
  });
});

describe('phone header CSS', () => {
  // .nav-btn loses its label below 760px and becomes a 36px icon square, so the
  // gap is the only boundary between destinations. It was 0.
  it('separates the icon-only nav buttons', () => {
    const media = css.match(/@media \(max-width: 760px\) \{[\s\S]*?\n\}/g) ?? [];
    const header = media.find((block) => block.includes('.header-actions'));
    expect(header).toMatch(/\.header-actions\s*\{[^}]*gap:\s*4px/);
  });

  // Measured against a preview build: with six items (an authenticated admin)
  // the gap pushes the theme toggle off-screen at 330px and under. The escape
  // hatch must come AFTER the 760px block — media queries add no specificity,
  // so reversed it loses and the narrow case silently keeps the gap.
  it('gives the space back below 340px, after the rule it overrides', () => {
    const narrow = css.indexOf('@media (max-width: 339px)');
    const wide = css.indexOf('@media (max-width: 760px)');
    expect(narrow).toBeGreaterThan(-1);
    expect(narrow).toBeGreaterThan(wide);
    const block = css.slice(narrow, css.indexOf('\n}', css.indexOf('.header-actions', narrow)) + 2);
    expect(block).toMatch(/\.header-actions\s*\{[^}]*gap:\s*0/);
  });
});

