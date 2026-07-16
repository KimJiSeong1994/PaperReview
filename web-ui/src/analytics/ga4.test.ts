import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ANALYTICS_CONSENT_STORAGE_KEY,
  initGA4,
  resetGA4ForTests,
  setAnalyticsConsent,
  trackEvent,
  trackPageView,
} from './ga4';

const enabledEnv = {
  VITE_ANALYTICS_ENABLED: 'true',
  VITE_GA_MEASUREMENT_ID: 'G-TEST123',
};

function storageWithConsent(value: string | null = null): Pick<Storage, 'getItem'> {
  return {
    getItem: vi.fn((key: string) => (key === ANALYTICS_CONSENT_STORAGE_KEY ? value : null)),
  };
}

function mutableStorageWithConsent(value: string | null = null): Pick<Storage, 'getItem' | 'setItem'> {
  let storedValue = value;
  return {
    getItem: vi.fn((key: string) => (key === ANALYTICS_CONSENT_STORAGE_KEY ? storedValue : null)),
    setItem: vi.fn((key: string, nextValue: string) => {
      if (key === ANALYTICS_CONSENT_STORAGE_KEY) storedValue = nextValue;
    }),
  };
}

describe('GA4 adapter', () => {
  beforeEach(() => {
    resetGA4ForTests();
    document.head.innerHTML = '';
  });

  afterEach(() => {
    resetGA4ForTests();
    vi.restoreAllMocks();
  });

  it('does not install gtag or scripts when env gates are disabled', () => {
    const win = {} as Window;

    expect(initGA4({ env: { VITE_ANALYTICS_ENABLED: 'false', VITE_GA_MEASUREMENT_ID: 'G-TEST123' }, win })).toBe(false);

    expect((win as Window & { dataLayer?: unknown }).dataLayer).toBeUndefined();
    expect(document.querySelector('script[src*="googletagmanager.com/gtag/js"]')).toBeNull();
  });

  it('applies denied consent default without loading GA script or config before opt-in', () => {
    const win = {} as Window;

    expect(initGA4({ env: enabledEnv, win, doc: document, storage: storageWithConsent() })).toBe(false);

    const dataLayer = (win as Window & { dataLayer: unknown[] }).dataLayer;
    expect(dataLayer[0]).toEqual([
      'consent',
      'default',
      {
        analytics_storage: 'denied',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
      },
    ]);
    expect(dataLayer.some((entry) => Array.isArray(entry) && entry[0] === 'config')).toBe(false);
    expect(document.querySelectorAll('script[src="https://www.googletagmanager.com/gtag/js?id=G-TEST123"]')).toHaveLength(0);
  });

  it('honors stored analytics consent while keeping advertising consent denied', () => {
    const win = {} as Window;

    initGA4({ env: enabledEnv, win, doc: document, storage: storageWithConsent('granted') });

    expect((win as Window & { dataLayer: unknown[] }).dataLayer[0]).toEqual([
      'consent',
      'default',
      expect.objectContaining({
        analytics_storage: 'granted',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
      }),
    ]);
    expect(document.querySelectorAll('script[src="https://www.googletagmanager.com/gtag/js?id=G-TEST123"]')).toHaveLength(1);
  });

  it('persists and updates analytics consent at runtime without enabling advertising storage', () => {
    const win = {} as Window;
    const storage = mutableStorageWithConsent();

    initGA4({ env: enabledEnv, win, doc: document, storage });
    expect(setAnalyticsConsent('granted', { env: enabledEnv, win, doc: document, storage })).toBe(true);
    expect(setAnalyticsConsent('denied', { env: enabledEnv, win, doc: document, storage })).toBe(true);

    const dataLayer = (win as Window & { dataLayer: unknown[] }).dataLayer;
    expect(storage.setItem).toHaveBeenCalledWith(ANALYTICS_CONSENT_STORAGE_KEY, 'granted');
    expect(storage.setItem).toHaveBeenCalledWith(ANALYTICS_CONSENT_STORAGE_KEY, 'denied');
    expect(dataLayer).toContainEqual([
      'consent',
      'update',
      {
        analytics_storage: 'granted',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
      },
    ]);
    expect(dataLayer).toContainEqual([
      'consent',
      'update',
      {
        analytics_storage: 'denied',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
      },
    ]);
    expect(dataLayer.findIndex((entry) => Array.isArray(entry) && entry[0] === 'consent' && entry[1] === 'update')).toBeLessThan(
      dataLayer.findIndex((entry) => Array.isArray(entry) && entry[0] === 'config'),
    );
  });

  it('dedupes script and initial config across repeated initialization', () => {
    const win = {} as Window;

    initGA4({ env: enabledEnv, win, doc: document, storage: storageWithConsent('granted') });
    initGA4({ env: enabledEnv, win, doc: document, storage: storageWithConsent('granted') });

    const dataLayer = (win as Window & { dataLayer: unknown[] }).dataLayer;
    expect(document.querySelectorAll('script[data-ga4-measurement-id="G-TEST123"]')).toHaveLength(1);
    expect(dataLayer.filter((entry) => Array.isArray(entry) && entry[0] === 'config')).toHaveLength(1);
  });

  it('suppresses page views and events while analytics consent is denied', () => {
    const win = {} as Window;
    const storage = storageWithConsent();

    expect(trackPageView(
      { page_path: '/', page_location: 'https://jiphyeonjeon.kr/' },
      { env: enabledEnv, win, doc: document, storage },
    )).toBe(false);
    expect(trackEvent('search', { query_length_bucket: 'short' }, { env: enabledEnv, win, doc: document, storage })).toBe(false);

    const dataLayer = (win as Window & { dataLayer: unknown[] }).dataLayer;
    expect(dataLayer.some((entry) => Array.isArray(entry) && entry[0] === 'event')).toBe(false);
    expect(dataLayer.some((entry) => Array.isArray(entry) && entry[0] === 'config')).toBe(false);
  });

  it('sends manual page views without raw query values', () => {
    const win = {} as Window;

    trackPageView(
      { page_path: '/', page_location: 'https://jiphyeonjeon.kr/' },
      { env: enabledEnv, win, doc: document, storage: storageWithConsent('granted') },
    );

    const payload = (win as Window & { dataLayer: unknown[] }).dataLayer.at(-1);
    // A page_view *event* (not a duplicate config) — a repeat config for an
    // already-configured id emits no GA4 hit, so this must be an event.
    expect(payload).toEqual(['event', 'page_view', { page_path: '/', page_location: 'https://jiphyeonjeon.kr/' }]);
    expect(JSON.stringify(payload)).not.toContain('private+paper+title');
    expect(JSON.stringify(payload)).not.toContain('?q=');
  });

  it('gates events through initialization', () => {
    const disabledWin = {} as Window;
    trackEvent('search', { query_length_bucket: 'short' }, { env: { VITE_ANALYTICS_ENABLED: 'false' }, win: disabledWin });
    expect((disabledWin as Window & { dataLayer?: unknown[] }).dataLayer).toBeUndefined();

    const enabledWin = {} as Window;
    trackEvent('search', { query_length_bucket: 'short' }, {
      env: enabledEnv,
      win: enabledWin,
      doc: document,
      storage: storageWithConsent('granted'),
    });
    expect((enabledWin as Window & { dataLayer: unknown[] }).dataLayer.at(-1)).toEqual([
      'event',
      'search',
      { query_length_bucket: 'short' },
    ]);
  });
});
