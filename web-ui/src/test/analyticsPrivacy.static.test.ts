import { describe, expect, it } from 'vitest';

const sourceModules = import.meta.glob('../**/*.{ts,tsx}', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, string>;

const analyticsSinkPattern = /\b(gtag|dataLayer|send_page_view|measurement_id|GA-\w|G-[A-Z0-9]+)\b/i;

const unsafeAnalyticsInputs: Array<[string, RegExp]> = [
  ['raw full URL', /\b(window\.location\.href|document\.URL)\b/],
  ['raw query/search params', /\b(location\.search|searchParams|URLSearchParams|\bq\b\s*[:=])\b/],
  ['share tokens', /\b(share\/?[:$`{]|token|access_token|jwt|Authorization)\b/i],
  ['admin or mypage routes', /['"`]\/(admin|mypage)\b/],
  ['localStorage identity fields', /localStorage\.(getItem|setItem)\(['"`](username|user_role|access_token)['"`]\)/],
  ['paper identifiers', /\b(paper_id|paperId|arxiv_id|doi|bookmarkId|curriculumId)\b/],
  ['paper titles or document titles', /\b(paperTitle|paper\.title|document\.title|page_title)\b/],
];

function analyticsSourceFiles(): Array<[string, string]> {
  return Object.entries(sourceModules).filter(([path, source]) => {
    if (path.includes('/test/') || /\.test\.[tj]sx?$/.test(path)) return false;
    return analyticsSinkPattern.test(source);
  });
}

function analyticsCallsiteFiles(): Array<[string, string]> {
  return Object.entries(sourceModules).filter(([path, source]) => {
    if (path.includes('/test/') || /\.test\.[tj]sx?$/.test(path)) return false;
    if (path.includes('/analytics/')) return false;
    return /analytics\/(events|ga4)/.test(source) || /\btrack[A-Z][A-Za-z]+\s*\(/.test(source);
  });
}

describe('analytics privacy static guard', () => {
  it('keeps analytics emitters away from raw query strings, tokens, identities, routes, and paper data', () => {
    const violations = analyticsSourceFiles().flatMap(([path, source]) =>
      unsafeAnalyticsInputs
        .filter(([, pattern]) => pattern.test(source))
        .map(([label]) => `${path}: analytics sink is coupled to ${label}`),
    );

    expect(violations).toEqual([]);
  });

  it('does not emit full URLs or raw route params through page view analytics', () => {
    const pageViewViolations = analyticsSourceFiles().flatMap(([path, source]) => {
      const hasPageView = /send_page_view|page_view|page_path|page_location/.test(source);
      if (!hasPageView) return [];

      const unsafePageViewInputs: Array<[string, RegExp]> = [
        ['raw params', /useParams\(|params\.|match\.params|:token|:id/],
        ['raw query', /location\.search|searchParams|URLSearchParams/],
        ['restricted route literals', /['"`]\/(admin|mypage|share)\b/],
        ['raw full URL', /window\.location\.href|document\.URL/],
      ];

      const unsafePageViewMatches = unsafePageViewInputs.filter(([, pattern]) => pattern.test(source));

      return unsafePageViewMatches.map(([label]) => `${path}: page view uses ${label}`);
    });

    expect(pageViewViolations).toEqual([]);
  });

  it('keeps production call sites on typed analytics wrappers instead of raw GA4 sinks', () => {
    const violations = analyticsCallsiteFiles().flatMap(([path, source]) => {
      const issues: string[] = [];
      const directGa4Import = /from ['"`]\.\.\/analytics\/ga4['"`]/.test(source);

      const allowedDirectGa4Import = path.endsWith('/components/AnalyticsRouteTracker.tsx')
        || path.endsWith('/components/AnalyticsConsentBanner.tsx');

      if (directGa4Import && !allowedDirectGa4Import) {
        issues.push(`${path}: imports GA4 adapter directly outside the route tracker`);
      }
      if (/\btrackGA4Event\s*\(/.test(source) || /\btrackEvent\s*\(/.test(source)) {
        issues.push(`${path}: calls raw analytics event sink`);
      }

      return issues;
    });

    expect(violations).toEqual([]);
  });
});
