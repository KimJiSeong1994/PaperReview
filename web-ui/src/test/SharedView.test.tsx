import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import SharedView from '../components/SharedView';
import { getSharedBookmark } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, getSharedBookmark: vi.fn() };
});

/**
 * The public share page composes an internal class:
 * `SharedView` renders `shared-view-report-content mypage-report-content`.
 * Every `.mypage-report-content` rule therefore ships to an unauthenticated,
 * indexed page. This file is the canary for that — it gates the CSS phases.
 *
 * What it does NOT do: jsdom applies no CSS, so a wrong font-size, a broken
 * colour or a lost `word-break` all pass here. Appearance is verified by hand
 * at /share/<token> in both themes.
 */
const REPORT = [
  '## 초록',
  '',
  '본문 문단입니다.',
  '',
  '| 모델 | 점수 |',
  '| --- | --- |',
  '| DeepWalk | 0.81 |',
  '',
  '```python',
  'print("hello")',
  '```',
  '',
  '<script>alert(1)</script>',
  '',
  '<div class="injected">xss</div>',
].join('\n');

const DATA = {
  id: 'bm_20260101_000000_abc',
  title: '공유 리포트',
  query: 'graph representation learning',
  papers: [],
  num_papers: 0,
  report_markdown: REPORT,
  created_at: '2026-01-01T00:00:00Z',
  tags: [],
  topic: 'General',
};

function renderShared() {
  return render(
    <MemoryRouter initialEntries={['/share/sh_testtoken']}>
      <Routes>
        <Route path="/share/:token" element={<SharedView />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('SharedView canary', () => {
  beforeEach(() => {
    vi.mocked(getSharedBookmark).mockResolvedValue(DATA as never);
  });

  it('composes the internal report class onto the public surface', async () => {
    const { container } = renderShared();
    await screen.findByText('공유 리포트');

    const content = container.querySelector('.shared-view-report-content');
    expect(content).not.toBeNull();
    // Non-exclusive on purpose: `.prose-base` joins these in Phase 4 and this
    // assertion must keep passing without being edited.
    expect(content).toHaveClass('shared-view-report-content', 'mypage-report-content');
  });

  it('renders the markdown pipeline intact', async () => {
    const { container } = renderShared();
    await screen.findByText('공유 리포트');

    const content = container.querySelector('.shared-view-report-content')!;
    expect(content.querySelector('h2')).not.toBeNull();
    expect(content.querySelector('table')).not.toBeNull();
    expect(content.querySelector('pre > code')).not.toBeNull();
    expect(content.querySelector('p')).not.toBeNull();
  });

  it('never turns raw markup into elements', async () => {
    const { container } = renderShared();
    await screen.findByText('공유 리포트');

    // No `rehypeRaw` on this surface. Assert on elements, not on text: react-markdown
    // escapes raw HTML to visible text rather than dropping it, so asserting the
    // text is absent would fail a correct build.
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('div.injected')).toBeNull();

    // Pin the escaping itself, so adding `rehypeRaw` later fails loudly here.
    const content = container.querySelector('.shared-view-report-content')!;
    await waitFor(() => expect(content.textContent).toContain('<script>alert(1)</script>'));
  });
});
