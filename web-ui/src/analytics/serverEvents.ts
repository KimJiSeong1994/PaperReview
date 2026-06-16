import { sanitizeRouteForAnalytics } from './routeSanitizer';
import type { AnalyticsEventName, AnalyticsEventParams } from './ga4';

const ANALYTICS_CONSENT_STORAGE_KEY = 'analytics_consent';
const ANALYTICS_CLIENT_ID_STORAGE_KEY = 'analytics_client_id';
const ANALYTICS_SESSION_ID_STORAGE_KEY = 'analytics_session_id';
const ALLOWED_PAYLOAD_KEYS = new Set([
  'query_length_bucket',
  'query_class',
  'result_status',
  'result_count_bucket',
  'selected_count_bucket',
  'source',
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_id',
  'utm_term',
  'utm_content',
  'page_type',
]);
const ATTRIBUTION_PAYLOAD_KEYS = new Set([
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_id',
  'utm_term',
  'utm_content',
  'page_type',
]);

function safeStorage(kind: 'localStorage' | 'sessionStorage'): Storage | undefined {
  try {
    return typeof window !== 'undefined' ? window[kind] : undefined;
  } catch {
    return undefined;
  }
}

function makeId(prefix: string): string {
  const randomId = globalThis.crypto?.randomUUID?.()
    ?? Math.random().toString(36).slice(2) + Date.now().toString(36);
  return `${prefix}_${randomId}`.slice(0, 96);
}

function getOrCreateId(storage: Storage | undefined, key: string, prefix: string): string {
  try {
    const existing = storage?.getItem(key);
    if (existing && /^[A-Za-z0-9._:-]{8,96}$/.test(existing)) return existing;
    const next = makeId(prefix);
    storage?.setItem(key, next);
    return next;
  } catch {
    return makeId(prefix);
  }
}

function hasGrantedConsent(): boolean {
  try {
    return safeStorage('localStorage')?.getItem(ANALYTICS_CONSENT_STORAGE_KEY) === 'granted';
  } catch {
    return false;
  }
}

function safeAttributionValue(value: string): string | null {
  const withoutControls = Array.from(value.trim()).filter((char) => {
    const code = char.charCodeAt(0);
    return code >= 32 && code !== 127;
  }).join('');
  if (!withoutControls || withoutControls.includes('@')) return null;

  const safeValue = withoutControls
    .slice(0, 128)
    .replace(/[^A-Za-z0-9._~%+-]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80);

  return safeValue || null;
}

function safePayload(params: AnalyticsEventParams): AnalyticsEventParams {
  const next: AnalyticsEventParams = {};
  for (const [key, value] of Object.entries(params)) {
    if (Object.keys(next).length >= 20) break;
    if (!ALLOWED_PAYLOAD_KEYS.has(key)
      && /(query|q|token|jwt|auth|password|email|title|user|paper|doi|arxiv|bookmark|curriculum)/i.test(key)) continue;
    if (typeof value === 'string' && ATTRIBUTION_PAYLOAD_KEYS.has(key)) {
      const safeValue = safeAttributionValue(value);
      if (safeValue) next[key] = safeValue;
    } else if (typeof value === 'string') next[key] = value.slice(0, 128);
    else if (typeof value === 'number' || typeof value === 'boolean') next[key] = value;
  }
  return next;
}

export function sendFirstPartyAnalyticsEvent(
  eventName: AnalyticsEventName | 'page_view',
  params: AnalyticsEventParams = {},
  pagePath?: string,
): boolean {
  if (typeof window === 'undefined' || typeof fetch === 'undefined') return false;
  if (!hasGrantedConsent()) return false;

  const origin = window.location?.origin;
  const sanitized = sanitizeRouteForAnalytics(pagePath ?? window.location?.pathname ?? '/', origin);
  if (!sanitized) return false;

  const local = safeStorage('localStorage');
  const session = safeStorage('sessionStorage');
  const token = local?.getItem('access_token');

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  void fetch('/api/analytics/events', {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    keepalive: true,
    body: JSON.stringify({
      client_id: getOrCreateId(local, ANALYTICS_CLIENT_ID_STORAGE_KEY, 'client'),
      session_id: getOrCreateId(session, ANALYTICS_SESSION_ID_STORAGE_KEY, 'session'),
      event_name: eventName,
      page_path: sanitized.pagePath,
      payload: safePayload(params),
    }),
  }).catch(() => {
    // Analytics must never break the product path.
  });

  return true;
}
