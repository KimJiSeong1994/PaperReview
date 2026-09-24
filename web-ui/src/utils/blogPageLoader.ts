let blogPageImport: ReturnType<typeof importBlogPage> | null = null;
let loadedBlogPage: typeof import('../components/BlogPage')['default'] | null = null;

function importBlogPage() {
  return import('../components/BlogPage');
}

/** Shared promise used by React.lazy and the SSR-preserving startup preload. */
export function preloadBlogPage() {
  blogPageImport ??= importBlogPage().then((module) => {
    loadedBlogPage = module.default;
    return module;
  });
  return blogPageImport;
}

/** A fulfilled import must render directly, without React.lazy's first suspend. */
export function getLoadedBlogPage() {
  return loadedBlogPage;
}
