import { describe, expect, it } from 'vitest';

// Chrome installs the app off the manifest alone — no service worker, no runtime
// code in this path. Every failure mode here is SILENT: a typo'd icon path, a
// missing field, or `prefer_related_applications: true` makes the omnibox
// install icon disappear with no console error and no failing build.

const manifestSource = Object.values(
  import.meta.glob('../../public/manifest.json', {
    eager: true,
    import: 'default',
    query: '?raw',
  }) as Record<string, string>,
)[0];

const indexHtml = Object.values(
  import.meta.glob('../../index.html', {
    eager: true,
    import: 'default',
    query: '?raw',
  }) as Record<string, string>,
)[0];

// Keys are the glob-relative paths ('../../public/icon-192.png'), so presence
// in this record is the file actually existing on disk.
const publicImages = import.meta.glob('../../public/*.png', { eager: true });

// Inlined as data URIs so the declared `sizes` can be checked against the real
// pixels. Only the files the manifest points at — globbing all of public/ would
// pull the multi-megabyte hero art into the test bundle. The test below fails if
// the manifest grows an image this list does not cover.
const pwaImages = import.meta.glob(
  '../../public/{icon-192,icon-512,screenshot-home,screenshot-introduce}.png',
  { eager: true, import: 'default', query: '?inline' },
) as Record<string, string>;

/** Width/height from a PNG IHDR, read off the front of a base64 data URI. */
function pngPixels(dataUri: string): [number, number] {
  const head = atob(dataUri.slice(dataUri.indexOf(',') + 1, dataUri.indexOf(',') + 1 + 64));
  const bytes = Uint8Array.from(head, (ch) => ch.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  return [view.getUint32(16), view.getUint32(20)];
}

/** Fails loudly rather than silently skipping an image the glob above misses. */
function declaredVsActual(src: string, sizes: string): void {
  const key = `../../public/${src.replace(/^\//, '')}`;
  expect(key in pwaImages, `${src} is not covered by the pwaImages glob`).toBe(true);
  const [width, height] = pngPixels(pwaImages[key]);
  expect(`${width}x${height}`, `${src} is not really ${sizes}`).toBe(sizes);
}

const manifest = JSON.parse(manifestSource) as {
  name?: string;
  short_name?: string;
  start_url?: string;
  display?: string;
  description?: string;
  prefer_related_applications?: boolean;
  icons?: Array<{ src: string; sizes: string; type?: string }>;
  screenshots?: Array<{
    src: string;
    sizes: string;
    type?: string;
    form_factor?: string;
    label?: string;
  }>;
};

describe('PWA manifest (Chrome installability)', () => {
  it('links the manifest from index.html at the path it is served from', () => {
    const link = indexHtml.match(/<link[^>]*rel="manifest"[^>]*>/);
    expect(link, 'index.html must carry <link rel="manifest">').not.toBeNull();
    // Vite copies public/ to the dist root verbatim, so href maps 1:1 onto the file.
    expect(link![0].match(/href="([^"]+)"/)?.[1]).toBe('/manifest.json');
  });

  it('declares the fields Chrome requires to offer an install', () => {
    expect(manifest.name || manifest.short_name).toBeTruthy();
    expect(manifest.start_url).toBe('/');
    expect(['fullscreen', 'standalone', 'minimal-ui', 'window-controls-overlay'])
      .toContain(manifest.display);
  });

  it('ships 192px and 512px icons that exist and really are those sizes', () => {
    for (const size of ['192x192', '512x512']) {
      const icon = manifest.icons?.find((candidate) => candidate.sizes === size);
      expect(icon, `manifest needs a ${size} icon`).toBeDefined();
      expect(
        `../../public/${icon!.src.replace(/^\//, '')}` in publicImages,
        `${icon!.src} is missing from web-ui/public/`,
      ).toBe(true);
      declaredVsActual(icon!.src, size);
    }
  });

  it('names the app the same thing every other identity surface does', () => {
    // The manifest name is the install dialog and launcher label — an identity
    // field, not a page title. It shipped as "집현전 — AI 논문 검색·리뷰", a
    // fourth string that matched neither the brand nor the title, and nothing
    // caught it. These are the other surfaces that name the same app.
    const siteName = indexHtml.match(
      /<meta property="og:site_name" content="([^"]+)"/,
    )?.[1];
    expect(siteName, 'index.html must declare og:site_name').toBeTruthy();
    expect(manifest.name).toBe(siteName);
    expect(manifest.short_name).toBe(siteName);

    // The JSON-LD WebApplication node describes the very app this manifest
    // installs, so its name has to agree too.
    const appNode = JSON.parse(
      indexHtml.match(/<script type="application\/ld\+json" id="home-json-ld">([\s\S]*?)<\/script>/)![1],
    )['@graph'].find((node: { '@type': string }) => node['@type'] === 'WebApplication');
    expect(appNode.name).toBe(manifest.name);
  });

  it('describes the app the same way the page description does', () => {
    const pageDescription = indexHtml.match(
      /<meta\s+name="description"\s*\n?\s*content="([^"]+)"/,
    )?.[1];
    expect(pageDescription, 'index.html must declare a meta description').toBeTruthy();
    expect(manifest.description).toBe(pageDescription);
  });

  it('ships screenshots Chrome will actually accept for the rich install dialog', () => {
    // Chrome silently falls back to the minimal "name + origin" dialog when any
    // of these fail — no console error, no build error. The rules (Chrome 109+):
    // desktop renders only form_factor "wide"; each side 320-3840px; the long
    // side at most 2.3x the short one; every screenshot in a form_factor group
    // must share one aspect ratio; PNG or JPEG only (WebP is not supported).
    const shots = manifest.screenshots ?? [];
    const wide = shots.filter((shot) => shot.form_factor === 'wide');
    expect(wide.length, 'desktop needs at least one form_factor "wide" screenshot').toBeGreaterThan(0);

    const ratios = new Set<number>();
    for (const shot of shots) {
      expect(shot.type, `${shot.src} must declare a type`).toMatch(/^image\/(png|jpeg)$/);
      expect(
        `../../public/${shot.src.replace(/^\//, '')}` in publicImages,
        `${shot.src} is missing from web-ui/public/`,
      ).toBe(true);
      declaredVsActual(shot.src, shot.sizes);

      const [width, height] = shot.sizes.split('x').map(Number);
      for (const side of [width, height]) {
        expect(side, `${shot.src} side out of Chrome's 320-3840 range`).toBeGreaterThanOrEqual(320);
        expect(side).toBeLessThanOrEqual(3840);
      }
      expect(
        Math.max(width, height) / Math.min(width, height),
        `${shot.src} is too elongated for Chrome (max 2.3x)`,
      ).toBeLessThanOrEqual(2.3);

      if (shot.form_factor === 'wide') ratios.add(width / height);
    }
    expect(ratios.size, 'every "wide" screenshot must share one aspect ratio').toBe(1);
  });

  it('does not steer users to a native app that does not exist', () => {
    // github.com/manifest.json sets this true to push Android users to its Play
    // Store app. Copying it here would suppress the Android install prompt.
    expect(manifest.prefer_related_applications).not.toBe(true);
  });
});
