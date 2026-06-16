const PRIVATE_ROUTE_PREFIXES = ['/mypage', '/admin', '/share'];
const BLOG_UTM_KEYS = [
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_id',
  'utm_term',
  'utm_content',
] as const;

export type FirstPartyPageViewPayload = Record<string, string | number | boolean>;

export type SanitizedPageView = {
  page_path: string;
  page_location: string;
  first_party_payload?: FirstPartyPageViewPayload;
};

export interface LegacySanitizedPageView {
  pagePath: string;
  pageLocation: string;
  pageTitle: string;
  firstPartyPayload?: FirstPartyPageViewPayload;
}

export type RouteLike = {
  pathname: string;
  search?: string;
  hash?: string;
};

function normalizePathname(pathname: string): string {
  if (!pathname || pathname === '*') return '/';

  const [withoutQuery] = pathname.split('?');
  const [withoutHash] = withoutQuery.split('#');
  const normalized = withoutHash.startsWith('/') ? withoutHash : `/${withoutHash}`;

  return normalized.replace(/\/{2,}/g, '/');
}

function isBlogPostPath(pathname: string): boolean {
  return /^\/blog\/[^/]+/.test(pathname);
}

function searchFromRoute(route: RouteLike): string {
  if (route.search) return route.search.split('#')[0] ?? '';
  const queryStart = route.pathname.indexOf('?');
  if (queryStart < 0) return '';
  return route.pathname.slice(queryStart).split('#')[0] ?? '';
}

function sanitizeAttributionValue(value: string): string | null {
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

export function extractBlogUtmPayload(route: RouteLike, pagePath?: string): FirstPartyPageViewPayload | undefined {
  const normalizedPagePath = pagePath ?? normalizePathname(route.pathname);
  if (!isBlogPostPath(normalizedPagePath)) return undefined;

  const search = searchFromRoute(route);
  if (!search) return undefined;

  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search);
  } catch {
    return undefined;
  }

  const payload: FirstPartyPageViewPayload = {};
  for (const key of BLOG_UTM_KEYS) {
    const value = params.get(key);
    if (!value) continue;
    const safeValue = sanitizeAttributionValue(value);
    if (safeValue) payload[key] = safeValue;
  }

  if (Object.keys(payload).length === 0) return undefined;
  payload.page_type = 'blog_post';
  return payload;
}

function decodePathForPrivacy(pathname: string): string {
  let decoded = pathname;
  for (let index = 0; index < 3; index += 1) {
    try {
      const nextDecoded = decodeURIComponent(decoded);
      if (nextDecoded === decoded) break;
      decoded = nextDecoded;
    } catch {
      break;
    }
  }

  return decoded.replace(/\\/g, '/').replace(/\/{2,}/g, '/').toLowerCase();
}

function isPrivateRoute(pathname: string): boolean {
  const privacyPathname = decodePathForPrivacy(pathname);
  return PRIVATE_ROUTE_PREFIXES.some((prefix) => (
    privacyPathname === prefix || privacyPathname.startsWith(`${prefix}/`)
  ));
}

function resolveOrigin(explicitOrigin?: string): string {
  if (explicitOrigin) return explicitOrigin.replace(/\/$/, '');

  if (typeof window !== 'undefined' && window.location.origin) {
    return window.location.origin.replace(/\/$/, '');
  }

  return '';
}

export function sanitizeRouteForPageView(route: RouteLike, origin?: string): SanitizedPageView | null {
  const pagePath = normalizePathname(route.pathname);

  if (isPrivateRoute(pagePath)) {
    return null;
  }

  const firstPartyPayload = extractBlogUtmPayload(route, pagePath);

  return {
    page_path: pagePath,
    page_location: `${resolveOrigin(origin)}${pagePath}`,
    ...(firstPartyPayload ? { first_party_payload: firstPartyPayload } : {}),
  };
}

export function sanitizeRouteForAnalytics(
  pathname: string,
  origin?: string,
  title: string = '',
): LegacySanitizedPageView | null {
  const sanitized = sanitizeRouteForPageView({ pathname }, origin);
  if (!sanitized) return null;

  return {
    pagePath: sanitized.page_path,
    pageLocation: sanitized.page_location,
    pageTitle: title,
    ...(sanitized.first_party_payload ? { firstPartyPayload: sanitized.first_party_payload } : {}),
  };
}
