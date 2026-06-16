const PRIVATE_ROUTE_PREFIXES = ['/mypage', '/admin', '/share'];

export type SanitizedPageView = {
  page_path: string;
  page_location: string;
};

export interface LegacySanitizedPageView {
  pagePath: string;
  pageLocation: string;
  pageTitle: string;
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

  return {
    page_path: pagePath,
    page_location: `${resolveOrigin(origin)}${pagePath}`,
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
  };
}
