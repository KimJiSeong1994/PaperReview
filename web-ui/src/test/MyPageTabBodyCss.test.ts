import { describe, expect, it } from 'vitest';
import css from '../components/MyPage.css?raw';

// jest-dom's toBeVisible() honours the `hidden` attribute by itself, so the
// rendered tests stay green even if the stylesheet stops hiding the wrapper —
// and then both tab bodies would render stacked. This is the one load-bearing
// rule, asserted where it lives.
describe('MyPage tab body CSS', () => {
  it('makes the wrapper box-less, and hides it when the hidden attribute is set', () => {
    expect(css).toMatch(/\.mypage-tab-body \{\s*display: contents;\s*\}/);
    expect(css).toMatch(/\.mypage-tab-body\[hidden\] \{\s*display: none;\s*\}/);
  });
});
