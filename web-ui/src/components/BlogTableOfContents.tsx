import { useEffect, useState } from 'react';

/** Scroll-spy line, in px from the viewport top. Also the sticky offset. */
const SPY_OFFSET = 80;

/**
 * The body's own table of contents, under either heading the corpus uses.
 * Shared with BlogPage, which hides these on wide screens.
 */
export const BODY_TOC_HEADINGS = new Set(['목차', 'Table of Contents']);

/**
 * H2s that are structural, not sections a reader would navigate to. Posts are
 * written in both Korean and English, and the same section carries either
 * label — skipping only one variant would list the summary on the 12 posts
 * that open with 핵심 요약 and omit it on the 50 that open with Executive
 * Summary.
 */
const SKIP_HEADINGS = new Set([
  'Executive Summary',
  '핵심 요약',
  'References',
  '참고문헌',
  ...BODY_TOC_HEADINGS,
]);

interface TocItem {
  id: string;
  text: string;
}

/**
 * Last heading to cross the line wins: of the headings at or above `offset`,
 * the one closest to it is the section currently being read. Returns null when
 * every heading is still below the line (caller keeps the previous value).
 */
export function chooseActiveId(
  positions: { id: string; top: number }[],
  offset: number,
): string | null {
  let best: { id: string; top: number } | null = null;
  for (const position of positions) {
    if (position.top <= offset && (!best || position.top > best.top)) best = position;
  }
  return best ? best.id : null;
}

/**
 * Sticky section index for the post detail view, built from the rendered
 * markdown rather than the source (rehype-slug has already assigned the ids we
 * link to). `postKey` re-extracts when the reader moves to another post.
 */
function BlogTableOfContents({ postKey }: { postKey: string }) {
  const [items, setItems] = useState<TocItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    setActiveId(null);

    const headings = Array.from(
      document.querySelectorAll<HTMLHeadingElement>('.blog-detail-content h2'),
    ).filter((heading) => heading.id && !SKIP_HEADINGS.has(heading.textContent?.trim() ?? ''));

    setItems(headings.map((heading) => ({ id: heading.id, text: heading.textContent?.trim() ?? '' })));
    if (headings.length === 0) return undefined;

    const observer = new IntersectionObserver(
      () => {
        const next = chooseActiveId(
          headings.map((heading) => ({ id: heading.id, top: heading.getBoundingClientRect().top })),
          SPY_OFFSET,
        );
        // Only ever replace: scrolling above the first heading should leave the
        // index highlighted where the reader last was, not blank.
        if (next) setActiveId(next);
      },
      { rootMargin: `-${SPY_OFFSET}px 0px 0px 0px` },
    );
    headings.forEach((heading) => observer.observe(heading));
    return () => observer.disconnect();
  }, [postKey]);

  if (items.length === 0) return null;

  return (
    <nav className="blog-toc" aria-label="목차">
      <div className="blog-toc-label">목차</div>
      <ul className="blog-toc-list">
        {items.map((item) => (
          <li key={item.id}>
            <a
              className={`blog-toc-link${item.id === activeId ? ' is-active' : ''}`}
              href={`#${item.id}`}
              aria-current={item.id === activeId ? 'location' : undefined}
            >
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default BlogTableOfContents;
