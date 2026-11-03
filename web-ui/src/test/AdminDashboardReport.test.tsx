import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import AdminDashboardReport from '../components/AdminDashboardReport';
import type { AdminDashboard } from '../api/client';

vi.mock('../PlotlyChart', () => ({
  default: () => <div data-testid="plot" />,
}));

const STATS: AdminDashboard = {
  total_users: 128,
  total_papers: 8420,
  total_bookmarks: 386,
  recent_review_sessions: 146,
  kg_nodes: 12450,
  kg_edges: 32780,
  papers_by_source: [
    { source: 'arXiv', count: 3820 },
    { source: 'OpenAlex', count: 2410 },
  ],
  papers_by_year: [
    { year: '2025', count: 1710 },
    { year: '2026', count: 720 },
  ],
  collection_queries: [{ query: 'dynamic word embeddings', count: 74 }],
  top_categories: [{ category: 'Natural Language Processing', count: 1680 }],
  recent_papers: [{
    title: 'Systematic Evaluation of Lexical Semantic Change',
    source: 'arXiv',
    collected_at: '2026-07-18T03:15:00Z',
  }],
  metric_definitions: {
    recent_review_sessions: {
      population: 'volatile_deep_review_jobs',
      ttl_hours: 24,
      durable: false,
    },
    collection_queries: {
      population: 'stored_papers_with_search_query',
      unit: 'papers',
      is_search_frequency: false,
    },
    paper_catalog: {
      source: 'raw_papers_json',
      relationship_to_users: 'none',
    },
  },
};

// jsdom's localStorage is broken in this setup; the rows read/write open state through this shim.
beforeEach(() => {
  const store: Record<string, string> = {};
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value); },
  });
});
afterEach(() => vi.unstubAllGlobals());

const row = (title: string) => screen.getByText(title, { selector: '.admin-details-title' }).closest('details') as HTMLDetailsElement;
const openRow = (title: string) => fireEvent.click(row(title).querySelector('summary')!);
const openAll = () => ['콘텐츠·지식 그래프 (레거시)', '수집 기여·분류', '최근 들어온 논문'].forEach(openRow);

describe('AdminDashboardReport', () => {
  it('renders three collapsed rows whose summaries carry the numbers, without the sentence cards', () => {
    render(<AdminDashboardReport stats={STATS} />);

    expect(row('콘텐츠·지식 그래프 (레거시)').open).toBe(false);
    expect(row('수집 기여·분류').open).toBe(false);
    expect(row('최근 들어온 논문').open).toBe(false);
    expect(screen.getByText('회원 128 · 논문 8,420 · 북마크 386')).toBeInTheDocument();
    expect(screen.getByText(/^쿼리 1 · 분야 1/)).toBeInTheDocument();
    expect(screen.getByText(`1편 · 최근 수집 ${new Date('2026-07-18T03:15:00Z').toLocaleDateString('ko-KR')}`)).toBeInTheDocument();
    expect(screen.queryByText('현재 운영 상태를 한 문장씩 읽어보세요')).toBeNull();
    expect(screen.queryByTestId('plot')).toBeNull();
  });

  it('shows the unchanged legacy content once the rows are opened', async () => {
    render(<AdminDashboardReport stats={STATS} />);
    openAll();

    // details fires toggle as a queued task, so the bodies appear after a tick.
    expect(await screen.findByText('최근 리뷰 작업')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '논문 수집 기여 쿼리 · 논문 수' })).toBeInTheDocument();
    expect(screen.getByText('dynamic word embeddings')).toBeInTheDocument();
    expect(screen.getByText('Natural Language Processing')).toBeInTheDocument();
    expect(screen.getByText('Systematic Evaluation of Lexical Semantic Change')).toBeInTheDocument();
    expect(await screen.findAllByTestId('plot')).toHaveLength(2);
  });

  it('shows clear empty states without losing the report structure', async () => {
    render(<AdminDashboardReport stats={{
      ...STATS,
      papers_by_source: [],
      papers_by_year: [],
      collection_queries: [],
      top_categories: [],
      recent_papers: [],
    }} />);
    openAll();

    expect(await screen.findByText('수집원 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('연도별 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('수집 쿼리 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('분류 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('최근 수집된 논문이 없습니다.')).toBeInTheDocument();
  });
});
