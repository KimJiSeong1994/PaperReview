import { useEffect } from 'react';
import { OG_DEFAULT_IMAGE } from '../seo/structuredData';

const MANAGED_ATTR = 'data-seo-managed';

export interface SEOHeadProps {
  title: string;
  description: string;
  canonical?: string;
  robots?: string;
  type?: string;
  image?: string;
  jsonLd?: Record<string, unknown>;
  publishedTime?: string;
  modifiedTime?: string;
  locale?: string;
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
  publishedTime,
  modifiedTime,
  locale = 'en_US',
}: SEOHeadProps) {
  useEffect(() => {
    removeManagedTags();
    document.title = title;

    const ogImage = image || OG_DEFAULT_IMAGE;

    upsertMeta('meta[name="description"]', { name: 'description', content: description });
    upsertMeta('meta[property="og:title"]', { property: 'og:title', content: title });
    upsertMeta('meta[property="og:description"]', { property: 'og:description', content: description });
    upsertMeta('meta[property="og:type"]', { property: 'og:type', content: type });
    upsertMeta('meta[property="og:site_name"]', { property: 'og:site_name', content: 'Jiphyeonjeon' });
    upsertMeta('meta[property="og:locale"]', { property: 'og:locale', content: locale });
    upsertMeta('meta[property="og:locale:alternate"]', {
      property: 'og:locale:alternate',
      content: locale === 'ko_KR' ? 'en_US' : 'ko_KR',
    });
    upsertMeta('meta[name="twitter:card"]', { name: 'twitter:card', content: 'summary_large_image' });
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

    upsertMeta('meta[property="og:image"]', { property: 'og:image', content: ogImage });
    upsertMeta('meta[property="og:image:width"]', { property: 'og:image:width', content: '1200' });
    upsertMeta('meta[property="og:image:height"]', { property: 'og:image:height', content: '630' });
    upsertMeta('meta[property="og:image:alt"]', { property: 'og:image:alt', content: title });
    upsertMeta('meta[name="twitter:image"]', { name: 'twitter:image', content: ogImage });
    upsertMeta('meta[name="twitter:image:alt"]', { name: 'twitter:image:alt', content: title });

    if (type === 'article') {
      if (publishedTime) {
        upsertMeta('meta[property="article:published_time"]', {
          property: 'article:published_time',
          content: publishedTime,
        });
      }
      if (modifiedTime) {
        upsertMeta('meta[property="article:modified_time"]', {
          property: 'article:modified_time',
          content: modifiedTime,
        });
      }
    }

    if (jsonLd) {
      upsertJsonLd(jsonLd);
    } else {
      removeManagedJsonLd();
    }

    return () => {
      removeManagedTags();
    };
  }, [canonical, description, image, jsonLd, locale, modifiedTime, publishedTime, robots, title, type]);

  return null;
}
