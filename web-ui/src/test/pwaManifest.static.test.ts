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

const manifest = JSON.parse(manifestSource) as {
  name?: string;
  short_name?: string;
  start_url?: string;
  display?: string;
  prefer_related_applications?: boolean;
  icons?: Array<{ src: string; sizes: string; type?: string }>;
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

  it('ships 192px and 512px icons that exist in public/', () => {
    for (const size of ['192x192', '512x512']) {
      const icon = manifest.icons?.find((candidate) => candidate.sizes === size);
      expect(icon, `manifest needs a ${size} icon`).toBeDefined();
      expect(
        `../../public/${icon!.src.replace(/^\//, '')}` in publicImages,
        `${icon!.src} is missing from web-ui/public/`,
      ).toBe(true);
    }
  });

  it('does not steer users to a native app that does not exist', () => {
    // github.com/manifest.json sets this true to push Android users to its Play
    // Store app. Copying it here would suppress the Android install prompt.
    expect(manifest.prefer_related_applications).not.toBe(true);
  });
});
