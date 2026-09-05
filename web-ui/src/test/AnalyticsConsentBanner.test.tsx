import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AnalyticsConsentBanner from '../components/AnalyticsConsentBanner';
import { __resetAnalyticsForTests, ANALYTICS_CONSENT_STORAGE_KEY } from '../analytics/ga4';

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

function setAnalyticsEnv(enabled = true) {
  vi.stubEnv('VITE_ANALYTICS_ENABLED', enabled ? 'true' : 'false');
  vi.stubEnv('VITE_GA_MEASUREMENT_ID', 'G-TEST123');
}

describe('AnalyticsConsentBanner', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    setAnalyticsEnv(true);
    installStorageShim();
    localStorage.clear();
    document.head.innerHTML = '';
    __resetAnalyticsForTests();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    __resetAnalyticsForTests();
  });

  it('renders an opt-in choice and wires Allow analytics to Consent Mode update', async () => {
    const user = userEvent.setup();

    render(<AnalyticsConsentBanner />);
    expect(screen.getByLabelText('사용 통계 수집 동의')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '수집 허용' }));

    expect(localStorage.getItem(ANALYTICS_CONSENT_STORAGE_KEY)).toBe('granted');
    expect(screen.queryByLabelText('사용 통계 수집 동의')).toBeNull();
    expect(window.dataLayer).toContainEqual([
      'consent',
      'update',
      expect.objectContaining({ analytics_storage: 'granted', ad_storage: 'denied' }),
    ]);
  });

  it('persists decline without loading the remote GA script', async () => {
    const user = userEvent.setup();

    render(<AnalyticsConsentBanner />);
    await user.click(screen.getByRole('button', { name: '동의 안 함' }));

    expect(localStorage.getItem(ANALYTICS_CONSENT_STORAGE_KEY)).toBe('denied');
    expect(document.querySelector('script[data-ga4-measurement-id="G-TEST123"]')).toBeNull();
  });

  it('stays hidden when analytics is disabled or a decision already exists', () => {
    setAnalyticsEnv(false);
    const { rerender } = render(<AnalyticsConsentBanner />);
    expect(screen.queryByLabelText('사용 통계 수집 동의')).toBeNull();

    setAnalyticsEnv(true);
    localStorage.setItem(ANALYTICS_CONSENT_STORAGE_KEY, 'denied');
    rerender(<AnalyticsConsentBanner />);
    expect(screen.queryByLabelText('사용 통계 수집 동의')).toBeNull();
  });
});
