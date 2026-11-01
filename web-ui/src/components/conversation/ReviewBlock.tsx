import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import type { VerificationStats } from '../../api/client';
import { useDeepReview } from '../../hooks/useDeepReview';
import type { ReviewStartedBlock } from '../../types';

// useDeepReview's placeholder before the first poll; the block shows it in Korean.
const HOOK_START_PROGRESS = 'Starting deep research...';

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
  const { reviewStatus, reviewProgress, startReview } = useDeepReview({
    onCompleted: (sessionId, markdown, stats) => onCompleted({ sessionId, title: block.paper_title, markdown, stats }),
  });

  useEffect(() => {
    startReview(block.session_id);
  }, [block.session_id, startReview]);

  return (
    <section className="conv-review" aria-label={`심층 리뷰: ${block.paper_title}`}>
      <p className="conv-review-title">{block.paper_title}</p>
      {reviewStatus === 'completed' ? (
        <div className="conv-review-row">
          <span className="home-chip is-completed">완료</span>
          <button type="button" className="conv-results-more" onClick={() => onOpenReport(block.session_id)}>
            리포트 보기 →
          </button>
        </div>
      ) : reviewStatus === 'failed' ? (
        <div className="conv-review-row" role="alert">
          <span className="home-chip is-failed">실패</span>
          <span className="conv-review-progress">{reviewProgress || '리뷰를 끝내지 못했어요.'}</span>
          <Link className="conv-results-more" to="/mypage">마이페이지에서 보기</Link>
        </div>
      ) : (
        <div className="conv-review-row" role="status">
          <span className="home-chip is-processing">진행 중</span>
          <span className="conv-review-progress">
            {!reviewProgress || reviewProgress === HOOK_START_PROGRESS ? '심층 리뷰를 시작하는 중…' : reviewProgress}
          </span>
        </div>
      )}
    </section>
  );
}

export default ReviewBlock;
