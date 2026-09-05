import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import SearchBar from '../components/SearchBar';
import searchBarCss from '../components/SearchBar.css?raw';

function renderBar() {
  return render(<SearchBar onSearch={vi.fn()} loading={false} />);
}

describe('SearchBar accessibility', () => {
  // The button's content is an emoji and it used to carry only title="Search".
  // Which of those a browser computed as the name was genuinely ambiguous —
  // accname puts name-from-content ahead of title — so it may well have been
  // announced as "magnifying glass tilted left". One explicit source settles it.
  it('names the submit button in Korean, not by its emoji', () => {
    renderBar();
    const button = screen.getByRole('button', { name: '논문 검색' });
    expect(button).toBeTruthy();
    expect(button.querySelector('.search-icon')?.getAttribute('aria-hidden')).toBe('true');
    expect(button.getAttribute('title')).toBeNull();
  });

  it('asks for a query in Korean', () => {
    renderBar();
    // Not a lang="en" annotation: this is a control on a Korean-language site,
    // not an English quotation.
    expect(screen.getByPlaceholderText('논문 검색')).toBeTruthy();
  });

  it('keeps the submit button out of the tab order until there is a query', () => {
    renderBar();
    expect(screen.getByRole('button', { name: '논문 검색' })).toBeDisabled();
  });

  // jsdom applies no CSS, so the focus indicator can only be checked at source
  // here. Measured in Chromium against a preview build, outline vs field:
  // dark 7.59:1, light 5.51:1 — both over the 3:1 WCAG 2.2 asks of a focus
  // indicator, against the 1.11:1 the old border-only treatment measured.
  it('gives the field a focus indicator that does not rely on the border alone', () => {
    const rule = searchBarCss.match(/\.search-input-wrapper:focus-within \{[^}]*\}/)?.[0];
    expect(rule).toBeTruthy();
    expect(rule).toMatch(/outline:\s*2px solid var\(--indigo\)/);
    expect(rule).toMatch(/outline-offset:/);
    // `.search-input { outline: none }` stays, so this rule is the only
    // indicator; if it ever stops carrying an outline the field has none.
    expect(searchBarCss).toMatch(/\.search-input \{[^}]*outline:\s*none/);
  });
});
