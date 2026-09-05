import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { render, within, fireEvent } from '@testing-library/react';
import TableOfContents from '../components/BlogTableOfContents';

/**
 * jsdom computes no layout, so every getBoundingClientRect is zeros. The scroll
 * arithmetic is the part of this component most likely to be wrong — it was
 * flagged in the plan's pre-mortem — so the rects are stubbed to stand in for a
 * real one.
 */
function stubRect(el: Element, top: number) {
  el.getBoundingClientRect = () => ({ top, bottom: top + 20, left: 0, right: 0,
    width: 0, height: 20, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
}

/** Query inside the rendered index only — the fixture headings carry the same
 *  text, so an unscoped query matches two nodes. */
function toc(container: HTMLElement) {
  return within(container);
}

function mountReport(markup: string) {
  const scroller = document.createElement('div');
  scroller.className = 'report-scroll';
  scroller.innerHTML = `<div class="report-content">${markup}</div>`;
  document.body.appendChild(scroller);
  return scroller;
}

afterEach(() => { document.body.innerHTML = ''; });

describe('TableOfContents', () => {
  it('collects h2 only by default, which is what the blog has always done', () => {
    mountReport('<h2 id="a">초록</h2><h3 id="b">1.1 배경</h3><h2 id="c">결론</h2>');
    const { container } = render(<TableOfContents postKey="k" containerSelector=".report-content" />);
    expect(toc(container).getByText('초록')).toBeInTheDocument();
    expect(toc(container).getByText('결론')).toBeInTheDocument();
    expect(toc(container).queryByText('1.1 배경')).toBeNull();
  });

  it('adds h3 at depth 3 and marks its level, so reports can nest 1.1 under 1', () => {
    mountReport('<h2 id="a">1. 서론</h2><h3 id="b">1.1 배경</h3>');
    const { container } = render(<TableOfContents postKey="k" containerSelector=".report-content" depth={3} />);
    expect(toc(container).getByText('1. 서론').getAttribute('data-level')).toBe('2');
    expect(toc(container).getByText('1.1 배경').getAttribute('data-level')).toBe('3');
  });

  it('skips the structural headings a reader would not navigate to', () => {
    mountReport('<h2 id="a">핵심 요약</h2><h2 id="b">참고문헌</h2><h2 id="c">본론</h2>');
    const { container } = render(<TableOfContents postKey="k" containerSelector=".report-content" />);
    expect(toc(container).queryByText('핵심 요약')).toBeNull();
    expect(toc(container).queryByText('참고문헌')).toBeNull();
    expect(toc(container).getByText('본론')).toBeInTheDocument();
  });

  it('renders nothing when the container holds no usable headings', () => {
    mountReport('<p>본문만 있습니다.</p>');
    const { container } = render(<TableOfContents postKey="k" containerSelector=".report-content" />);
    expect(container.firstChild).toBeNull();
  });

  describe('clicking an entry', () => {
    let scroller: HTMLElement;

    beforeEach(() => {
      scroller = mountReport('<h2 id="target">2. 방법론</h2>');
      stubRect(scroller, 100);            // container top edge at y=100
      stubRect(document.getElementById('target')!, 500); // heading 400px below it
      scroller.scrollTop = 40;
    });

    it('moves the container by the gap between heading and container, less the spy offset', () => {
      const { container } = render(
        <TableOfContents postKey="k" containerSelector=".report-content"
          scrollRootSelector=".report-scroll" />,
      );
      fireEvent.click(toc(container).getByText('2. 방법론'));
      // 40 (current) + 400 (delta) - 8 (offset) = 432
      expect(scroller.scrollTop).toBe(432);
    });

    it('prevents the default hash jump, which would write to the URL', () => {
      const { container } = render(
        <TableOfContents postKey="k" containerSelector=".report-content"
          scrollRootSelector=".report-scroll" />,
      );
      const link = toc(container).getByText('2. 방법론');
      const event = new MouseEvent('click', { bubbles: true, cancelable: true });
      link.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
    });

    it('leaves the blog alone: with no scroll root it keeps the native anchor jump', () => {
      const { container } = render(<TableOfContents postKey="k" containerSelector=".report-content" />);
      const link = toc(container).getByText('2. 방법론');
      const event = new MouseEvent('click', { bubbles: true, cancelable: true });
      link.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
      expect(scroller.scrollTop).toBe(40);
    });
  });
});

describe('scroll-spy inside a container', () => {
  let scroller: HTMLElement;
  let headings: HTMLElement[];

  beforeEach(() => {
    scroller = mountReport(
      '<h2 id="one">1. 서론</h2><h2 id="two">2. 방법론</h2><h2 id="three">3. 결과</h2>',
    );
    stubRect(scroller, 0);
    headings = ['one', 'two', 'three'].map((id) => document.getElementById(id)!);
  });

  /** Move every heading up by `by` px, as scrolling the container would. */
  function scrollBy(by: number) {
    const layout = [100, 600, 1100];
    headings.forEach((h, i) => stubRect(h, layout[i] - by));
    act(() => { scroller.dispatchEvent(new Event('scroll')); });
  }

  it('highlights the heading the reader has reached, and follows further scrolling', async () => {
    const { container } = render(
      <TableOfContents postKey="k" containerSelector=".report-content"
        scrollRootSelector=".report-scroll" />,
    );
    const activeText = () =>
      container.querySelector('.blog-toc-link.is-active')?.textContent?.trim() ?? null;

    scrollBy(150);   // first heading is now above the line
    await new Promise((r) => setTimeout(r, 30));
    expect(activeText()).toBe('1. 서론');

    scrollBy(700);   // second one crosses
    await new Promise((r) => setTimeout(r, 30));
    expect(activeText()).toBe('2. 방법론');

    scrollBy(1200);  // third
    await new Promise((r) => setTimeout(r, 30));
    expect(activeText()).toBe('3. 결과');
  });

  it('keeps the last heading highlighted when the reader scrolls back above the first', async () => {
    const { container } = render(
      <TableOfContents postKey="k" containerSelector=".report-content"
        scrollRootSelector=".report-scroll" />,
    );
    const activeText = () =>
      container.querySelector('.blog-toc-link.is-active')?.textContent?.trim() ?? null;

    scrollBy(700);
    await new Promise((r) => setTimeout(r, 30));
    expect(activeText()).toBe('2. 방법론');

    scrollBy(0);     // everything back below the line
    await new Promise((r) => setTimeout(r, 30));
    expect(activeText()).toBe('2. 방법론');
  });
});
