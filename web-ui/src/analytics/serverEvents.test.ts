import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { sendFirstPartyAnalyticsEvent } from './serverEvents';

function installStorage(name: 'localStorage' | 'sessionStorage', initial: Record<string, string> = {}) {
  const store = { ...initial };
  const shim: Storage = {
    getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: (key) => { delete store[key]; },
    clear: () => { for (const key of Object.keys(store)) delete store[key]; },
    key: (index) => Object.keys(store)[index] ?? null,
    get length() { return Object.keys(store).length; },
  };
  Object.defineProperty(window, name, { configurable: true, writable: true, value: shim });
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value: shim });
}

describe('first-party analytics event mirror', () => {
  beforeEach(() => {
    installStorage('localStorage', { analytics_consent: 'granted', access_token: 'jwt-token' });
    installStorage('sessionStorage');
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 202 }))));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('sends sanitized consented events with auth header but without sensitive payload keys', () => {
    expect(sendFirstPartyAnalyticsEvent('search', {
      query_length_bucket: '11-30',
      query: 'raw paper title',
      result_count_bucket: '1-5',
      utm_source: 'alice@example.com',
      utm_campaign: 'Paper Review 2026!',
    }, '/blog/post?x=1')).toBe(true);

    expect(fetch).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({ Authorization: 'Bearer jwt-token' });
    const body = JSON.parse(String(init.body));
    expect(body.event_name).toBe('search');
    expect(body.page_path).toBe('/blog/post');
    expect(body.payload).toEqual({
      query_length_bucket: '11-30',
      result_count_bucket: '1-5',
      utm_campaign: 'Paper_Review_2026',
    });
    expect(body.client_id).toMatch(/^client_/);
    expect(body.session_id).toMatch(/^session_/);
  });

  it('does not send anything without analytics consent', () => {
    localStorage.setItem('analytics_consent', 'denied');
    expect(sendFirstPartyAnalyticsEvent('page_view', {}, '/')).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });
});
