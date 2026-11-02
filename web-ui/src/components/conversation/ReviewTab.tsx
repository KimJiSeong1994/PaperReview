import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  classifyPosterError,
  classifyPosterResponse,
  downloadPosterPdf,
  generatePoster,
  generatePosterDirect,
  getReviewReport,
  getVerificationDetail,
  type ClassifiedPosterResponse,
  type ReviewReportResponse,
  type VerificationDetailResponse,
} from '../../api/review';
import { claimEvidence, verificationStatusLabel } from './conversationBlocks';

interface ReviewTabProps {
  sessionId: string;
  title: string;
}

type LoadState = 'loading' | 'ready' | 'gone' | 'pending' | 'error';

const httpStatusOf = (error: unknown): number | undefined => (error as { response?: { status?: number } })?.response?.status;

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};

/**
 * The conversation's one place for a deep review: report, claim-level
 * verification, poster and export. Mount with `key={sessionId}`.
 */
function ReviewTab({ sessionId, title }: ReviewTabProps) {
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [report, setReport] = useState<ReviewReportResponse | null>(null);
  const [verification, setVerification] = useState<VerificationDetailResponse | null>(null);
  const [verificationFailed, setVerificationFailed] = useState(false);
  const [poster, setPoster] = useState<{ html: string; warning: string | null } | null>(null);
  const [posterBusy, setPosterBusy] = useState(false);
  const [posterError, setPosterError] = useState<string | null>(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getReviewReport(sessionId)
      .then(data => {
        if (cancelled) return;
        setReport(data);
        setLoadState('ready');
        return getVerificationDetail(sessionId)
          .then(detail => { if (!cancelled) setVerification(detail); })
          .catch(() => { if (!cancelled) setVerificationFailed(true); });
      })
      .catch(error => {
        if (cancelled) return;
        const status = httpStatusOf(error);
        // Sessions live in server memory (restart, 24h TTL): 404 is final, as in ReviewBlock.
        setLoadState(status === 404 ? 'gone' : status === 400 ? 'pending' : 'error');
      });
    return () => { cancelled = true; };
  }, [sessionId]);

  const makePoster = async () => {
    if (!report) return;
    setPosterBusy(true);
    setPosterError(null);
    const direct = async () => classifyPosterResponse(await generatePosterDirect(report.report_markdown, report.num_papers || 1));
    try {
      let result: ClassifiedPosterResponse;
      try {
        result = classifyPosterResponse(await generatePoster(sessionId));
        // The session's poster path can be unavailable while its report is not; the report is enough.
        if (!result.canPreview && result.canUseDirectFallback) result = await direct();
      } catch (error) {
        if (!classifyPosterError(error).canUseDirectFallback) throw error;
        result = await direct();
      }
      if (result.canPreview) {
        setPoster({
          html: result.posterHtml,
          warning: result.status === 'degraded'
            ? result.warning || '포스터가 일부 제한된 상태로 만들어졌어요. 내용을 확인한 뒤 사용하세요.'
            : null,
        });
      } else {
        setPosterError(`포스터를 만들지 못했어요. ${result.error || ''}`.trim());
      }
    } catch (error) {
      setPosterError(`포스터를 만들지 못했어요. ${classifyPosterError(error).error || ''}`.trim());
    } finally {
      setPosterBusy(false);
    }
  };

  const downloadPdf = async () => {
    if (!poster) return;
    setPdfBusy(true);
    setPdfError(null);
    try {
      const { blob, filename } = await downloadPosterPdf(poster.html);
      saveBlob(blob, filename);
    } catch (error) {
      const failure = classifyPosterError(error);
      setPdfError(failure.errorCode === 'poster_pdf_unavailable'
        ? '이 서버는 PDF 내보내기를 지원하지 않아요.'
        : `PDF를 만들지 못했어요. ${failure.error || ''}`.trim());
    } finally {
      setPdfBusy(false);
    }
  };

  const exportMarkdown = () => {
    if (!report) return;
    const safeTitle = title.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'review';
    saveBlob(new Blob([report.report_markdown], { type: 'text/markdown' }), `${safeTitle}.md`);
  };

  if (loadState === 'loading') return <p className="conv-artifact-empty" role="status">리뷰를 불러오는 중…</p>;
  if (loadState === 'gone') {
    return (
      <p className="conv-artifact-empty" role="status">
        <span className="home-chip">확인 불가</span> 리뷰 세션을 더 이상 찾을 수 없어요. 다시 요청하면 새로 시작합니다.
      </p>
    );
  }
  if (loadState === 'pending') return <p className="conv-artifact-empty" role="status">리뷰가 아직 끝나지 않았어요. 끝나면 여기서 볼 수 있어요.</p>;
  if (loadState === 'error' || !report) return <p className="conv-artifact-empty" role="alert">리뷰를 불러오지 못했어요.</p>;

  const stats = report.verification_stats ?? verification?.verification_stats ?? null;
  const claims = verification?.claims ?? [];

  return (
    <div className="conv-report">
      <div className="conv-report-actions">
        <button type="button" className="conv-btn" onClick={exportMarkdown}>.md 내보내기</button>
      </div>
      {stats && stats.total_claims > 0 && (
        <p className="conv-report-stats">
          근거 확인 {Math.round(stats.verification_rate * 100)}% · 주장 {stats.total_claims}개 중
          확인 {stats.verified} · 부분 {stats.partially_verified} · 미확인 {stats.unverified}
          {stats.contradicted > 0 && ` · 반박 ${stats.contradicted}`}
        </p>
      )}
      <div className="conv-markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.report_markdown}</ReactMarkdown>
      </div>

      <section className="conv-report-section" aria-labelledby={`verify-${sessionId}`}>
        <h3 id={`verify-${sessionId}`} className="conv-report-heading">검증 상세</h3>
        {verificationFailed ? (
          <p className="conv-note">검증 상세를 불러오지 못했어요.</p>
        ) : !verification ? (
          <p className="conv-note" role="status">검증 상세를 불러오는 중…</p>
        ) : claims.length === 0 && !stats ? (
          // Fast reviews (the chat default) skip claim verification entirely.
          <p className="conv-note">빠른 리뷰에는 주장 검증 단계가 없어요. &lsquo;정밀 리뷰 해줘&rsquo;라고 요청하면 주장 검증까지 수행합니다.</p>
        ) : claims.length === 0 ? (
          <p className="conv-note">검증한 주장이 없어요.</p>
        ) : (
          <table className="conv-claims">
            <thead>
              <tr><th scope="col">주장</th><th scope="col">상태</th><th scope="col">근거</th></tr>
            </thead>
            <tbody>
              {claims.map(claim => {
                const status = verificationStatusLabel(claim.verification_status ?? claim.evidences?.[0]?.verification_status);
                return (
                  <tr key={claim.id}>
                    <td>{claim.text}</td>
                    <td>{status ? <span className={`conv-claim-status is-${claim.verification_status ?? claim.evidences?.[0]?.verification_status}`}>{status}</span> : '—'}</td>
                    <td>{claimEvidence(claim) ?? '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="conv-report-section" aria-labelledby={`poster-${sessionId}`}>
        <h3 id={`poster-${sessionId}`} className="conv-report-heading">포스터</h3>
        {!poster ? (
          <>
            <button type="button" className="conv-btn conv-btn-primary" onClick={makePoster} disabled={posterBusy}>
              {posterBusy ? '포스터 만드는 중…' : '포스터 생성'}
            </button>
            {posterError && <p className="conv-error-text" role="alert">{posterError}</p>}
          </>
        ) : (
          <>
            {poster.warning && <p className="conv-note">{poster.warning}</p>}
            <div className="conv-report-actions">
              <button type="button" className="conv-btn" onClick={downloadPdf} disabled={pdfBusy}>
                {pdfBusy ? 'PDF 만드는 중…' : 'PDF 내려받기'}
              </button>
            </div>
            {pdfError && <p className="conv-error-text" role="alert">{pdfError}</p>}
            {/* Same sandboxed preview as the search page's poster modal. */}
            <iframe className="conv-poster" srcDoc={poster.html} sandbox="" title={`${title} 포스터 미리보기`} />
          </>
        )}
      </section>
    </div>
  );
}

export default ReviewTab;
