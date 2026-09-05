import { useEffect, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';

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
  /** 2 or 3 — drives the indent, and nothing else. */
  level: number;
}

interface TableOfContentsProps {
  /** Re-extracts when the reader moves to another post or report. */
  postKey: string;
  /** Where the rendered markdown lives. */
  containerSelector?: string;
  /** 2 collects h2 only (the blog is flat); 3 adds h3 (reports nest 1.1 under 1). */
  depth?: 2 | 3;
  /**
   * Selector for the element that scrolls, when it is not the window. The blog
   * scrolls the page; the report scrolls inside a div, which changes both what
   * the observer watches and what offsets are measured against. A selector
   * rather than a ref, because a ref is still null on the first render and the
   * effect that needs this runs after mount, when the query just works.
   */
  scrollRootSelector?: string;
  /** Class stem, so the two surfaces can look different without forking logic. */
  classPrefix?: string;
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
 * Sticky section index, built from the rendered markdown rather than the source
 * (rehype-slug has already assigned the ids we link to). `postKey` re-extracts
 * when the reader moves to another post or report.
 */
function BlogTableOfContents({
  postKey,
  containerSelector = '.blog-detail-content',
  depth = 2,
  scrollRootSelector,
  classPrefix = 'blog-toc',
}: TableOfContentsProps) {
  const [items, setItems] = useState<TocItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  // Inside a scroll container the line sits just below its top edge; on the page
  // it clears the sticky header.
  const spyOffset = scrollRootSelector ? 8 : SPY_OFFSET;
  const findScroller = () =>
    (scrollRootSelector ? document.querySelector<HTMLElement>(scrollRootSelector) : null);

  useEffect(() => {
    setActiveId(null);

    const selector = depth >= 3
      ? `${containerSelector} h2, ${containerSelector} h3`
      : `${containerSelector} h2`;
    const headings = Array.from(
      document.querySelectorAll<HTMLHeadingElement>(selector),
    ).filter((heading) => heading.id && !SKIP_HEADINGS.has(heading.textContent?.trim() ?? ''));

    setItems(headings.map((heading) => ({
      id: heading.id,
      text: heading.textContent?.trim() ?? '',
      level: heading.tagName === 'H3' ? 3 : 2,
    })));
    if (headings.length === 0) return undefined;

    const scroller = findScroller();

    // Positions are measured against whatever is scrolling: the viewport for the
    // page, the container's own top edge for a panel.
    const topsRelativeToScroller = () => {
      const origin = scroller ? scroller.getBoundingClientRect().top : 0;
      return headings.map((heading) => ({
        id: heading.id,
        top: heading.getBoundingClientRect().top - origin,
      }));
    };

    // Only ever replace: scrolling above the first heading should leave the
    // index highlighted where the reader last was, not blank.
    const update = () => {
      const next = chooseActiveId(topsRelativeToScroller(), spyOffset);
      if (next) setActiveId(next);
    };

    if (scroller) {
      /**
       * A scroll listener rather than an IntersectionObserver, because the
       * observer does not fire for elements inside this panel — measured in
       * production: zero callbacks for a connected heading whose ancestor is
       * the scroller, with `root` set to the scroller or to the viewport, with
       * and without a rootMargin, while a plain div on the same page fired
       * normally. The scroll event always fires, and the position maths is
       * unchanged. Coalesced to one read per frame: `update` measures every
       * heading, and a long report has dozens.
       */
      let frame = 0;
      const onScroll = () => {
        if (frame) return;
        frame = requestAnimationFrame(() => { frame = 0; update(); });
      };
      update();
      scroller.addEventListener('scroll', onScroll, { passive: true });
      return () => {
        scroller.removeEventListener('scroll', onScroll);
        if (frame) cancelAnimationFrame(frame);
      };
    }

    // The page-scrolling blog keeps the observer, which works there and is
    // cheaper than measuring on every scroll.
    const observer = new IntersectionObserver(
      update,
      { root: null, rootMargin: `-${spyOffset}px 0px 0px 0px` },
    );
    headings.forEach((heading) => observer.observe(heading));
    return () => observer.disconnect();
  }, [postKey, containerSelector, depth, scrollRootSelector, spyOffset]);

  if (items.length === 0) return null;

  /**
   * Inside a container, assign `scrollTop` directly. Neither the native hash
   * jump nor `scrollIntoView({behavior:'smooth'})` can be relied on to move an
   * `overflow-y` element — verified elsewhere in this codebase — and a hash
   * would also write to a URL that carries state of its own. The page-scrolling
   * blog keeps the native behaviour it has always had.
   */
  const handleClick = (event: ReactMouseEvent<HTMLAnchorElement>, id: string) => {
    const scroller = findScroller();
    if (!scroller) return;
    event.preventDefault();
    const heading = document.getElementById(id);
    if (!heading) return;
    const delta = heading.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
    scroller.scrollTop += delta - spyOffset;
    setActiveId(id);
  };

  return (
    <nav className={classPrefix} aria-label="목차">
      <div className={`${classPrefix}-label`}>목차</div>
      <ul className={`${classPrefix}-list`}>
        {items.map((item) => (
          <li key={item.id}>
            <a
              className={`${classPrefix}-link${item.id === activeId ? ' is-active' : ''}`}
              href={`#${item.id}`}
              data-level={item.level}
              onClick={(event) => handleClick(event, item.id)}
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
