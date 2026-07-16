import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import AnalyticsRouteTracker from '../components/AnalyticsRouteTracker';
import { sanitizeRouteForAnalytics } from '../analytics/routeSanitizer';
import {
  __resetAnalyticsForTests,
  initializeAnalytics,
  setAnalyticsConsent,
  trackPageView,
} from '../analytics/ga4';
import { trackSearchEvent } from '../analytics/events';


function installStorageShim(): void {
  const store: Record<string, string> = {};
  const shim: Storage = {
    getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: (key) => { delete store[key]; },
    clear: () => { for (const key of Object.keys(store)) delete store[key]; },
    key: (index) => Object.keys(store)[index] ?? null,
    get length() { return Object.keys(store).length; },
  };
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, writable: true, value: shim });
  Object.defineProperty(window, 'localStorage', { configurable: true, writable: true, value: shim });
}

function pushedEvents() {
  return (window.dataLayer || []) as unknown[][];
}

function setAnalyticsEnv(enabled = true) {
  vi.stubEnv('VITE_ANALYTICS_ENABLED', enabled ? 'true' : 'false');
  vi.stubEnv('VITE_GA_MEASUREMENT_ID', 'G-TEST123');
  vi.stubEnv('VITE_GA_DEBUG', 'true');
}

describe('GA4 privacy-safe measurement', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    setAnalyticsEnv(true);
    installStorageShim();
    document.head.innerHTML = '';
    document.title = 'Test Page';
    localStorage.clear();
    __resetAnalyticsForTests();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('sanitizes page locations by stripping query/hash and suppressing private token routes', () => {
    expect(sanitizeRouteForAnalytics('/?q=private+paper', 'https://example.test')).toEqual({
      pagePath: '/',
      pageLocation: 'https://example.test/',
      pageTitle: '',
    });
    expect(sanitizeRouteForAnalytics('/blog/public-slug?draft=1#section', 'https://example.test')).toMatchObject({
      pagePath: '/blog/public-slug',
      pageLocation: 'https://example.test/blog/public-slug',
    });
    expect(sanitizeRouteForAnalytics('/share/secret-token', 'https://example.test')).toBeNull();
    expect(sanitizeRouteForAnalytics('/share/curriculum/secret-token', 'https://example.test')).toBeNull();
    expect(sanitizeRouteForAnalytics('/mypage', 'https://example.test')).toBeNull();
    expect(sanitizeRouteForAnalytics('/admin', 'https://example.test')).toBeNull();
  });

  it('does not load scripts or emit hits unless analytics is explicitly enabled', () => {
    setAnalyticsEnv(false);
    expect(initializeAnalytics()).toBe(false);
    trackPageView('/');

    expect(document.head.querySelector('script[src*="googletagmanager.com"]')).toBeNull();
    expect(pushedEvents()).toEqual([]);
  });

  it('applies denied consent without configuring GA before opt-in', () => {
    expect(initializeAnalytics()).toBe(false);

    expect(document.head.querySelector('script[data-ga4-measurement-id="G-TEST123"]')).toBeNull();
    expect(pushedEvents()[0]).toEqual([
      'consent',
      'default',
      {
        analytics_storage: 'denied',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
      },
    ]);
    expect(pushedEvents().some((event) => event[0] === 'config')).toBe(false);
  });

  it('persists explicit analytics consent changes and emits Consent Mode updates', () => {
    expect(setAnalyticsConsent('granted')).toBe(true);
    expect(localStorage.getItem('analytics_consent')).toBe('granted');
    expect(setAnalyticsConsent('denied')).toBe(true);
    expect(localStorage.getItem('analytics_consent')).toBe('denied');

    expect(pushedEvents()).toContainEqual([
      'consent',
      'update',
      {
        analytics_storage: 'granted',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
      },
    ]);
    expect(pushedEvents()).toContainEqual([
      'consent',
      'update',
      {
        analytics_storage: 'denied',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
      },
    ]);
  });

  it('emits deduped page_view events without raw query strings or private tokens', () => {
    setAnalyticsConsent('granted');

    trackPageView('/?q=raw paper title');
    trackPageView('/?q=different raw title');
    trackPageView('/share/private-token');
    trackPageView('/blog/public-slug?utm_source=x');

    const pageViews = pushedEvents().filter((event) => event[0] === 'event' && event[1] === 'page_view');
    expect(pageViews).toHaveLength(2);
    expect(pageViews[0]?.[2]).toMatchObject({ page_path: '/', page_location: 'http://localhost:3000/' });
    expect(pageViews[1]?.[2]).toMatchObject({
      page_path: '/blog/public-slug',
      page_location: 'http://localhost:3000/blog/public-slug',
    });
    expect(JSON.stringify(pageViews)).not.toContain('raw paper title');
    expect(JSON.stringify(pageViews)).not.toContain('private-token');
  });

  it('sends search event buckets but never sends raw query text', () => {
    setAnalyticsConsent('granted');

    trackSearchEvent('privacy preserving federated learning', 'success', 12, 'home');

    const searchEvent = pushedEvents().find((event) => event[0] === 'event' && event[1] === 'search');
    expect(searchEvent?.[2]).toMatchObject({
      query_length_bucket: '31-80',
      query_class: 'latin',
      result_status: 'success',
      result_count_bucket: '6-20',
      source: 'home',
    });
    expect(JSON.stringify(searchEvent)).not.toContain('privacy preserving federated learning');
  });

  it('tracks route changes once per sanitized public path', async () => {
    setAnalyticsConsent('granted');

    function RouteButtons() {
      const navigate = useNavigate();
      return (
        <>
          <AnalyticsRouteTracker />
          <button type="button" onClick={() => navigate('/?q=secret')}>Home</button>
          <button type="button" onClick={() => navigate('/blog/public')}>Blog</button>
          <button type="button" onClick={() => navigate('/share/token-123')}>Share</button>
        </>
      );
    }

    const user = userEvent.setup();
    const { getByRole } = render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="*" element={<RouteButtons />} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(getByRole('button', { name: 'Home' }));
    await user.click(getByRole('button', { name: 'Blog' }));
    await user.click(getByRole('button', { name: 'Share' }));

    const pageViews = pushedEvents().filter(
      (event) => event[0] === 'event'
        && event[1] === 'page_view'
        && Boolean((event[2] as Record<string, unknown> | undefined)?.page_path),
    );
    expect(pageViews).toHaveLength(2);
    expect(pageViews[0]?.[2]).toMatchObject({ page_path: '/', page_location: 'http://localhost:3000/' });
    expect(pageViews[1]?.[2]).toMatchObject({
      page_path: '/blog/public',
      page_location: 'http://localhost:3000/blog/public',
    });
    expect(JSON.stringify(pageViews)).not.toContain('secret');
    expect(JSON.stringify(pageViews)).not.toContain('token-123');
  });
});
