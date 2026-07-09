export function buildPdfSrc(pdfUrl: string): string {
  const trimmed = pdfUrl.trim();

  if (!trimmed) return trimmed;

  // Already same-origin. Keep local/proxied URLs untouched so authenticated and
  // internal viewer flows do not double-proxy an API route.
  if (trimmed.startsWith('/') && !trimmed.startsWith('//')) {
    return trimmed;
  }

  try {
    const url = new URL(trimmed);
    const currentOrigin = globalThis.window?.location?.origin;
    if (currentOrigin && url.origin === currentOrigin) {
      return `${url.pathname}${url.search}${url.hash}`;
    }
  } catch {
    // Invalid or non-absolute value. Preserve previous behavior by letting the
    // backend reject it through the proxy endpoint instead of failing in UI code.
  }

  // Always proxy external PDFs, including arXiv. React-PDF/pdf.js fetches the
  // file from the browser/worker, so direct academic-host URLs can fail because
  // of CORS even when curl succeeds. The same-origin proxy also centralizes SSRF
  // allow-listing and PDF streaming behavior.
  return `/api/pdf/proxy?url=${encodeURIComponent(trimmed)}`;
}
