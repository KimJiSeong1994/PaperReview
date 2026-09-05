import '@testing-library/jest-dom';

/**
 * jsdom ships no IntersectionObserver, so every component that observes one
 * depends on a test stubbing it. `BlogPage.detail.test.tsx` does exactly that,
 * per-test, and unstubs in `afterEach` — which leaves a window where a React
 * passive effect can still mount and find the global gone. CI hit it once:
 * `ReferenceError: IntersectionObserver is not defined` from
 * BlogTableOfContents, inside commitHookPassiveMountEffects, on a commit that
 * touched neither file and passed on a straight re-run.
 *
 * A default here closes that window: the global is always something, so the
 * failure mode cannot occur regardless of stub lifecycle. Tests that care about
 * observer behaviour still override it with `vi.stubGlobal`.
 *
 * Honest caveat: the race was not reproducible locally (12 runs isolated, 10
 * under CPU load, all green), so this is reasoned from the stack trace rather
 * than demonstrated against a failing case.
 */
if (!('IntersectionObserver' in globalThis)) {
  class NoopIntersectionObserver implements IntersectionObserver {
    readonly root = null;
    readonly rootMargin = '';
    readonly thresholds: readonly number[] = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] { return []; }
  }
  globalThis.IntersectionObserver = NoopIntersectionObserver;
}
