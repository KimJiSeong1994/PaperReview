import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { VerificationStats } from '../../api/client';
import { useDeepReview } from '../../hooks/useDeepReview';
import type { ReviewStartedBlock } from '../../types';
import { reviewProgressLabel } from './conversationBlocks';

export interface CompletedReview {
  sessionId: string;
  title: string;
  markdown: string;
  stats?: VerificationStats;
}

interface ReviewBlockProps {
  block: ReviewStartedBlock;
  onCompleted: (review: CompletedReview) => void;
  onOpenReport: (sessionId: string) => void;
}

/**
 * A deep review started from the conversation. It polls the session (via the
 * search page's useDeepReview) until it completes or fails; a reloaded
 * conversation resumes polling, and a finished session settles on the first poll.
 */
function ReviewBlock({ block, onCompleted, onOpenReport }: ReviewBlockProps) {
  // Sessions live in server memory (lost on restart, 24h TTL): a 404 is final.
  const [gone, setGone] = useState(false);
  const { reviewStatus, reviewProgress, startReview } = useDeepReview({
    onCompleted: (sessionId, markdown, stats) => onCompleted({ sessionId, title: block.paper_title, markdown, stats }),
    onStatusError: status => {
      if (status !== 404) return false;
      setGone(true);
      return true;
    },
  });

  useEffect(() => {
    startReview(block.session_id);
  }, [block.session_id, startReview]);

  return (
    <section className="conv-review" aria-label={`심층 리뷰: ${block.paper_title}`}>
      <p className="conv-review-title">{block.paper_title}</p>
      {gone ? (
        <div className="conv-review-row" role="status">
          <span className="home-chip">확인 불가</span>
          <span className="conv-review-progress">리뷰 세션을 더 이상 찾을 수 없어요. 다시 요청하면 새로 시작합니다.</span>
        </div>
      ) : reviewStatus === 'completed' ? (
        <div className="conv-review-row">
          <span className="home-chip is-completed">완료</span>
          <button type="button" className="conv-results-more" onClick={() => onOpenReport(block.session_id)}>
            리포트 보기 →
          </button>
        </div>
      ) : reviewStatus === 'failed' ? (
        <div className="conv-review-row" role="alert">
          <span className="home-chip is-failed">실패</span>
          {/* The raw error stays in the tooltip; it can be an exception string. */}
          <span className="conv-review-progress" title={reviewProgress || undefined}>심층 리뷰에 실패했어요.</span>
          <Link className="conv-results-more" to="/mypage">마이페이지에서 보기</Link>
        </div>
      ) : (
        <div className="conv-review-row" role="status">
          <span className="home-chip is-processing">진행 중</span>
          <span className="conv-review-progress">{reviewProgressLabel(reviewProgress)}</span>
        </div>
      )}
    </section>
  );
}

export default ReviewBlock;
