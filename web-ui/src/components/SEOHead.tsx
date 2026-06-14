import { useEffect } from 'react';

const MANAGED_ATTR = 'data-seo-managed';

export interface SEOHeadProps {
  title: string;
  description: string;
  canonical?: string;
  robots?: string;
  type?: string;
  image?: string;
  jsonLd?: Record<string, unknown>;
}

function upsertMeta(selector: string, attrs: Record<string, string>) {
  let element = document.head.querySelector<HTMLMetaElement>(selector);
  if (!element) {
    element = document.createElement('meta');
    document.head.appendChild(element);
  }
  element.setAttribute(MANAGED_ATTR, 'true');
  for (const [key, value] of Object.entries(attrs)) {
    element.setAttribute(key, value);
  }
}

function upsertCanonical(href: string) {
  let element = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!element) {
    element = document.createElement('link');
    element.setAttribute('rel', 'canonical');
    document.head.appendChild(element);
  }
  element.setAttribute(MANAGED_ATTR, 'true');
  element.setAttribute('href', href);
}

function upsertJsonLd(data: Record<string, unknown>) {
  const id = 'seo-json-ld';
  let element = document.head.querySelector<HTMLScriptElement>(`script#${id}`);
  if (!element) {
    element = document.createElement('script');
    element.id = id;
    element.type = 'application/ld+json';
    document.head.appendChild(element);
  }
  element.setAttribute(MANAGED_ATTR, 'true');
  element.textContent = JSON.stringify(data);
}

function removeManagedJsonLd() {
  document.head.querySelector('script#seo-json-ld')?.remove();
}

function removeManagedTags() {
  document.head.querySelectorAll(`[${MANAGED_ATTR}="true"]`).forEach((element) => element.remove());
}

export default function SEOHead({
  title,
  description,
  canonical,
  robots,
  type = 'website',
  image,
  jsonLd,
}: SEOHeadProps) {
  useEffect(() => {
    removeManagedTags();
    document.title = title;

    upsertMeta('meta[name="description"]', { name: 'description', content: description });
    upsertMeta('meta[property="og:title"]', { property: 'og:title', content: title });
    upsertMeta('meta[property="og:description"]', { property: 'og:description', content: description });
    upsertMeta('meta[property="og:type"]', { property: 'og:type', content: type });
    upsertMeta('meta[name="twitter:card"]', { name: 'twitter:card', content: image ? 'summary_large_image' : 'summary_large_image' });
    upsertMeta('meta[name="twitter:title"]', { name: 'twitter:title', content: title });
    upsertMeta('meta[name="twitter:description"]', { name: 'twitter:description', content: description });

    if (canonical) {
      upsertCanonical(canonical);
      upsertMeta('meta[property="og:url"]', { property: 'og:url', content: canonical });
    }

    if (robots) {
      upsertMeta('meta[name="robots"]', { name: 'robots', content: robots });
    } else {
      document.head.querySelector('meta[name="robots"]')?.remove();
    }

    if (image) {
      upsertMeta('meta[property="og:image"]', { property: 'og:image', content: image });
      upsertMeta('meta[name="twitter:image"]', { name: 'twitter:image', content: image });
    } else {
      document.head.querySelector('meta[property="og:image"]')?.remove();
      document.head.querySelector('meta[name="twitter:image"]')?.remove();
    }

    if (jsonLd) {
      upsertJsonLd(jsonLd);
    } else {
      removeManagedJsonLd();
    }

    return () => {
      removeManagedTags();
    };
  }, [canonical, description, image, jsonLd, robots, title, type]);

  return null;
}
