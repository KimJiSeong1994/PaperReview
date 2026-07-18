import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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

describe('AdminDashboardReport', () => {
  it('renders the conclusion-first report and every operational chapter', async () => {
    render(<AdminDashboardReport stats={STATS} />);

    expect(screen.getByRole('heading', { name: '서비스 운영 리포트' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '현재 운영 상태를 한 문장씩 읽어보세요' })).toBeInTheDocument();
    expect(screen.getByText('128명 등록 · 8,420편 보유')).toBeInTheDocument();
    expect(screen.getByText('386개 저장 · 146개 리뷰 작업')).toBeInTheDocument();
    expect(screen.getByText('12,450개 노드 · 32,780개 연결')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '콘텐츠와 지식 그래프' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '수집 기여와 분류' })).toBeInTheDocument();
    expect(screen.getByText('최근 리뷰 작업')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '논문 수집 기여 쿼리 · 논문 수' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '최근 들어온 논문' })).toBeInTheDocument();
    expect(screen.getByText('dynamic word embeddings')).toBeInTheDocument();
    expect(screen.getByText('Natural Language Processing')).toBeInTheDocument();
    expect(screen.getByText('Systematic Evaluation of Lexical Semantic Change')).toBeInTheDocument();
    expect(await screen.findAllByTestId('plot')).toHaveLength(2);
  });

  it('shows clear empty states without losing the report structure', () => {
    render(<AdminDashboardReport stats={{
      ...STATS,
      papers_by_source: [],
      papers_by_year: [],
      collection_queries: [],
      top_categories: [],
      recent_papers: [],
    }} />);

    expect(screen.getByText('수집원 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('연도별 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('수집 쿼리 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('분류 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('최근 수집된 논문이 없습니다.')).toBeInTheDocument();
  });
});
