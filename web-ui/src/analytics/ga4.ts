import { extractBlogUtmPayload, sanitizeRouteForAnalytics } from './routeSanitizer';
import { sendFirstPartyAnalyticsEvent } from './serverEvents';
import type { FirstPartyPageViewPayload } from './routeSanitizer';

export const ANALYTICS_CONSENT_STORAGE_KEY = 'analytics_consent';
export const ANALYTICS_CONSENT_CHANGED_EVENT = 'analytics-consent-changed';

export type AnalyticsConsent = 'granted' | 'denied';

export type AnalyticsEnv = {
  VITE_ANALYTICS_ENABLED?: string;
  VITE_GA_MEASUREMENT_ID?: string;
  VITE_GA_DEBUG?: string;
};

type GtagCommand = [command: 'js', date: Date]
  | [command: 'config', targetId: string, config?: Record<string, unknown>]
  | [command: 'consent', consentCommand: 'default' | 'update', params: Record<string, string>]
  | [command: 'event', eventName: string, params?: Record<string, unknown>];

type AnalyticsWindow = Window & {
  dataLayer?: GtagCommand[];
  gtag?: (...args: GtagCommand) => void;
};

declare global {
  interface Window {
    dataLayer?: GtagCommand[];
    gtag?: (...args: GtagCommand) => void;
  }
}

export type PageViewPayload = {
  page_path: string;
  page_location: string;
  first_party_payload?: FirstPartyPageViewPayload;
};

export interface AnalyticsEventParams {
  [key: string]: string | number | boolean | undefined;
}

type AnalyticsStorage = Pick<Storage, 'getItem'> & Partial<Pick<Storage, 'setItem'>>;

export type GA4Options = {
  env?: AnalyticsEnv;
  win?: AnalyticsWindow;
  doc?: Document;
  storage?: AnalyticsStorage;
};

let initializedMeasurementId: string | null = null;
let consentDefaultApplied = false;
let lastPagePath: string | null = null;

const GA4_EVENT_NAMES = [
  'search',
  'paper_select',
  'login',
  'sign_up',
  'deep_review_start',
  'deep_review_complete',
  'deep_review_fail',
  'bookmark_save',
  'report_download',
  'poster_generate_start',
  'poster_generate_complete',
  'poster_generate_fail',
] as const;

export type AnalyticsEventName = typeof GA4_EVENT_NAMES[number];
const GA4_EVENT_NAME_SET = new Set<string>(GA4_EVENT_NAMES);

function getDefaultEnv(): AnalyticsEnv {
  return {
    VITE_ANALYTICS_ENABLED: import.meta.env.VITE_ANALYTICS_ENABLED,
    VITE_GA_MEASUREMENT_ID: import.meta.env.VITE_GA_MEASUREMENT_ID,
    VITE_GA_DEBUG: import.meta.env.VITE_GA_DEBUG,
  };
}

function isEnabled(value: string | undefined): boolean {
  return value === 'true' || value === '1';
}

function getStoredAnalyticsConsent(storage?: Pick<Storage, 'getItem'>): AnalyticsConsent {
  return getStoredAnalyticsConsentState(storage) ?? 'denied';
}

export function getStoredAnalyticsConsentState(storage?: Pick<Storage, 'getItem'>): AnalyticsConsent | null {
  try {
    const value = storage?.getItem(ANALYTICS_CONSENT_STORAGE_KEY);
    return value === 'granted' || value === 'denied' ? value : null;
  } catch {
    return null;
  }
}

function persistAnalyticsConsent(
  consent: AnalyticsConsent,
  storage?: Partial<Pick<Storage, 'setItem'>>,
): void {
  try {
    storage?.setItem?.(ANALYTICS_CONSENT_STORAGE_KEY, consent);
  } catch {
    // Storage can be unavailable in private browsing or tests; keep runtime consent update best-effort.
  }
}

function consentParams(consent: AnalyticsConsent): Record<string, string> {
  return {
    analytics_storage: consent,
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
  };
}

function hasGrantedAnalyticsConsent(storage?: Pick<Storage, 'getItem'>): boolean {
  return getStoredAnalyticsConsent(storage) === 'granted';
}

function notifyAnalyticsConsentChanged(win: AnalyticsWindow | undefined, consent: AnalyticsConsent): void {
  try {
    win?.dispatchEvent?.(
      new CustomEvent(ANALYTICS_CONSENT_CHANGED_EVENT, {
        detail: { consent },
      }),
    );
  } catch {
    // Event dispatch is a progressive enhancement for route re-tracking after opt-in.
  }
}

function getRuntime(options: GA4Options) {
  const win = options.win ?? (typeof window !== 'undefined' ? (window as AnalyticsWindow) : undefined);
  const doc = options.doc ?? (typeof document !== 'undefined' ? document : undefined);
  const storage = options.storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);

  return { win, doc, storage };
}

function installGtag(win: AnalyticsWindow): void {
  win.dataLayer = win.dataLayer ?? [];
  win.gtag = win.gtag ?? ((...args: GtagCommand) => {
    win.dataLayer?.push(args);
  });
}

function applyConsentDefault(win: AnalyticsWindow, storage?: Pick<Storage, 'getItem'>): void {
  if (consentDefaultApplied) return;

  win.gtag?.('consent', 'default', consentParams(getStoredAnalyticsConsent(storage)));
  consentDefaultApplied = true;
}

function loadGtagScript(doc: Document, measurementId: string): void {
  const existingScript = doc.querySelector<HTMLScriptElement>(
    `script[data-ga4-measurement-id="${measurementId}"]`,
  );
  if (existingScript) return;

  const script = doc.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
  script.dataset.ga4MeasurementId = measurementId;
  doc.head.appendChild(script);
}

export function isGA4Configured(env: AnalyticsEnv = getDefaultEnv()): boolean {
  return isEnabled(env.VITE_ANALYTICS_ENABLED) && Boolean(env.VITE_GA_MEASUREMENT_ID);
}

export function initGA4(options: GA4Options = {}): boolean {
  const env = options.env ?? getDefaultEnv();
  const measurementId = env.VITE_GA_MEASUREMENT_ID;

  if (!isEnabled(env.VITE_ANALYTICS_ENABLED) || !measurementId) {
    return false;
  }

  const { win, doc, storage } = getRuntime(options);
  if (!win || !doc) return false;

  installGtag(win);
  applyConsentDefault(win, storage);

  if (!hasGrantedAnalyticsConsent(storage)) {
    return false;
  }

  if (initializedMeasurementId === measurementId) {
    return true;
  }

  loadGtagScript(doc, measurementId);
  win.gtag?.('js', new Date());
  win.gtag?.('config', measurementId, {
    send_page_view: false,
    ...(isEnabled(env.VITE_GA_DEBUG) ? { debug_mode: true } : {}),
  });
  initializedMeasurementId = measurementId;

  return true;
}

export function initializeAnalytics(): boolean {
  return initGA4();
}

export function setAnalyticsConsent(consent: AnalyticsConsent, options: GA4Options = {}): boolean {
  const { win, storage } = getRuntime(options);

  persistAnalyticsConsent(consent, storage);

  if (consent === 'denied') {
    win?.gtag?.('consent', 'update', consentParams(consent));
    notifyAnalyticsConsentChanged(win, consent);
    return true;
  }

  if (win) {
    installGtag(win);
    applyConsentDefault(win, storage);
    win.gtag?.('consent', 'update', consentParams(consent));
  }

  if (!initGA4(options)) {
    notifyAnalyticsConsentChanged(win, consent);
    return false;
  }

  notifyAnalyticsConsentChanged(win, consent);
  return true;
}

function isSafePageViewPayload(pageView: PageViewPayload): boolean {
  if (!pageView.page_path.startsWith('/')) return false;
  if (/[?#]/.test(pageView.page_path) || /[?#]/.test(pageView.page_location)) return false;
  return sanitizeRouteForAnalytics(pageView.page_path, '') !== null;
}

export function trackPageView(pageView: PageViewPayload, options?: GA4Options): boolean;
export function trackPageView(pathname: string, title?: string): boolean;
export function trackPageView(pageViewOrPath: PageViewPayload | string, optionsOrTitle: GA4Options | string = {}): boolean {
  const options = typeof pageViewOrPath === 'string' ? {} : optionsOrTitle as GA4Options;
  const env = options.env ?? getDefaultEnv();
  const measurementId = env.VITE_GA_MEASUREMENT_ID;

  if (!measurementId || !initGA4(options)) return false;

  const { win } = getRuntime(options);
  if (typeof pageViewOrPath === 'string') {
    const title = typeof optionsOrTitle === 'string' ? optionsOrTitle : undefined;
    const origin = typeof window !== 'undefined' ? window.location.origin : undefined;
    const sanitized = sanitizeRouteForAnalytics(pageViewOrPath, origin, title);
    if (!sanitized || sanitized.pagePath === lastPagePath) return false;

    win?.gtag?.('event', 'page_view', {
      page_location: sanitized.pageLocation,
      page_path: sanitized.pagePath,
      ...(isEnabled(env.VITE_GA_DEBUG) ? { debug_mode: true } : {}),
    });
    lastPagePath = sanitized.pagePath;
    sendFirstPartyAnalyticsEvent(
      'page_view',
      sanitized.firstPartyPayload ?? extractBlogUtmPayload({ pathname: pageViewOrPath }, sanitized.pagePath) ?? {},
      sanitized.pagePath,
    );
    return true;
  }

  if (!isSafePageViewPayload(pageViewOrPath)) return false;

  // Send an explicit page_view *event* — not a repeat gtag('config'). The
  // initial config sets send_page_view:false, and GA4 ignores a duplicate
  // config for an already-configured id, so a config here emits no hit and GA4
  // records nothing. This branch (used by AnalyticsRouteTracker) must mirror
  // the string overload above.
  win?.gtag?.('event', 'page_view', {
    page_path: pageViewOrPath.page_path,
    page_location: pageViewOrPath.page_location,
    ...(isEnabled(env.VITE_GA_DEBUG) ? { debug_mode: true } : {}),
  });
  lastPagePath = pageViewOrPath.page_path;
  sendFirstPartyAnalyticsEvent('page_view', pageViewOrPath.first_party_payload ?? {}, pageViewOrPath.page_path);
  return true;
}

function trackGA4Event(
  eventName: string,
  params: Record<string, unknown> = {},
  options: GA4Options = {},
): boolean {
  if (!initGA4(options)) return false;

  const { win } = getRuntime(options);
  win?.gtag?.('event', eventName, params);
  sendFirstPartyAnalyticsEvent(eventName as AnalyticsEventName, params as AnalyticsEventParams);
  return true;
}

export function trackEvent(
  eventName: AnalyticsEventName,
  params: AnalyticsEventParams = {},
  options?: GA4Options,
): boolean {
  if (!GA4_EVENT_NAME_SET.has(eventName)) return false;
  return trackGA4Event(eventName, params, options);
}

export function resetGA4ForTests(): void {
  initializedMeasurementId = null;
  consentDefaultApplied = false;
  lastPagePath = null;
}

export function __resetAnalyticsForTests(): void {
  resetGA4ForTests();
  if (typeof window !== 'undefined') {
    delete (window as AnalyticsWindow).gtag;
    window.dataLayer = [];
  }
}
