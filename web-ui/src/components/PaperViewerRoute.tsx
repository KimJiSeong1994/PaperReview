import { lazy, Suspense, useMemo } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import LazyLoadErrorBoundary from './LazyLoadErrorBoundary';
import SEOHead from './SEOHead';
import './PaperViewerRoute.css';

const PaperViewerPanel = lazy(() => import('./mypage/PaperViewerPanel'));

const SITE_URL = 'https://jiphyeonjeon.kr';

function splitAuthors(value: string | null): string[] {
  return value
    ?.split(';')
    .map((author) => author.trim())
    .filter(Boolean) ?? [];
}

function parseYear(value: string | null): number | undefined {
  if (!value) return undefined;
  const year = Number(value);
  return Number.isFinite(year) ? year : undefined;
}

function normalizeUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      return url.toString();
    }
  } catch {
    return undefined;
  }
  return undefined;
}

export default function PaperViewerRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);

  const paper = useMemo(() => {
    const title = params.get('title')?.trim();
    if (!title) return null;

    return {
      title,
      authors: splitAuthors(params.get('authors')),
      year: parseYear(params.get('year')),
      pdf_url: normalizeUrl(params.get('pdf_url')),
      doi: params.get('doi')?.trim() || undefined,
      arxiv_id: params.get('arxiv_id')?.trim() || undefined,
      url: normalizeUrl(params.get('url')),
      source: params.get('source')?.trim() || 'blog-reference',
    };
  }, [params]);

  const pageTitle = paper ? `${paper.title} | Jiphyeonjeon Paper Viewer` : 'Paper Viewer | Jiphyeonjeon';
  const canonical = `${SITE_URL}/paper-viewer${location.search}`;

  return (
    <main className="paper-viewer-route">
      <SEOHead
        title={pageTitle}
        description="집현전 Paper Viewer에서 논문 PDF를 바로 읽고 확인합니다."
        canonical={canonical}
        // Every shared PDF link is a unique ?title=…&pdf_url=… combo; keep these
        // thin, near-duplicate viewer pages out of the index (follow so the
        // links still pass) so they don't dilute crawl budget for /blog.
        robots="noindex,follow"
      />
      <header className="paper-viewer-route-header">
        <button className="paper-viewer-route-back" onClick={() => navigate(-1)} type="button">
          ← 돌아가기
        </button>
        <Link className="paper-viewer-route-brand" to="/blog">
          <span className="paper-viewer-route-brand-mark">集</span>
          <span>Jiphyeonjeon Paper Viewer</span>
        </Link>
      </header>

      {paper ? (
        <section className="paper-viewer-route-body" aria-label={`${paper.title} PDF viewer`}>
          <div className="paper-viewer-route-titlebar">
            <div>
              <p className="paper-viewer-route-kicker">Blog Reference PDF</p>
              <h1>{paper.title}</h1>
              {(paper.authors.length > 0 || paper.year) && (
                <p className="paper-viewer-route-meta">
                  {paper.authors.slice(0, 4).join(', ')}{paper.authors.length > 4 ? ' et al.' : ''}
                  {paper.year ? `${paper.authors.length > 0 ? ' · ' : ''}${paper.year}` : ''}
                </p>
              )}
            </div>
          </div>

          <div className="paper-viewer-route-panel-wrap">
            <LazyLoadErrorBoundary>
              <Suspense fallback={<div className="paper-viewer-route-loading">뷰어 불러오는 중...</div>}>
                <PaperViewerPanel
                  bookmarkDetail={{ papers: [paper] }}
                  loadingDetail={false}
                  hasSelectedBookmark={true}
                  autoSelectFirst={true}
                />
              </Suspense>
            </LazyLoadErrorBoundary>
          </div>
        </section>
      ) : (
        <section className="paper-viewer-route-empty">
          <h1>논문 정보를 찾을 수 없습니다</h1>
          <p>블로그의 PDF 보기 링크에 논문 제목 또는 PDF 정보가 포함되어 있는지 확인해 주세요.</p>
          <Link to="/blog">블로그로 이동</Link>
        </section>
      )}
    </main>
  );
}
