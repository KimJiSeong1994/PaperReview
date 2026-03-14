import { useState, useEffect, useCallback, useRef } from 'react';
import { getReviewStatus, getReviewReport } from '../api/client';
import type { VerificationStats } from '../api/client';

type DeepReviewStatus = 'idle' | 'processing' | 'completed' | 'failed';

interface UseDeepReviewOptions {
  /** Called when the review completes. Receives session ID, report markdown, and verification stats. */
  onCompleted?: (sessionId: string, reportMarkdown: string, verificationStats?: VerificationStats) => void;
  /** Called when the review fails. */
  onFailed?: (error: string) => void;
  /** Auto-reset delay in ms after completed/failed. 0 = no auto-reset. */
  autoResetDelay?: number;
}

export function useDeepReview(options: UseDeepReviewOptions = {}) {
  const { onCompleted, onFailed, autoResetDelay = 0 } = options;

  const [reviewSessionId, setReviewSessionId] = useState<string | null>(null);
  const [reviewStatus, setReviewStatus] = useState<DeepReviewStatus>('idle');
  const [reviewProgress, setReviewProgress] = useState('');
  const [reviewReport, setReviewReport] = useState<string | null>(null);
  const [verificationStats, setVerificationStats] = useState<VerificationStats | null>(null);

  // Stable refs for callbacks to avoid re-creating the effect
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;
  const onFailedRef = useRef(onFailed);
  onFailedRef.current = onFailed;

  const startReview = useCallback((sessionId: string) => {
    setReviewSessionId(sessionId);
    setReviewStatus('processing');
    setReviewProgress('Starting deep research...');
    setReviewReport(null);
    setVerificationStats(null);
  }, []);

  const resetReview = useCallback(() => {
    setReviewSessionId(null);
    setReviewStatus('idle');
    setReviewProgress('');
    setReviewReport(null);
    setVerificationStats(null);
  }, []);

  // Poll review status
  useEffect(() => {
    if (!reviewSessionId || reviewStatus !== 'processing') return;

    const pollInterval = setInterval(async () => {
      try {
        const status = await getReviewStatus(reviewSessionId);
        setReviewProgress(status.progress || 'Analyzing papers...');

        if (status.status === 'completed') {
          clearInterval(pollInterval);
          try {
            const report = await getReviewReport(reviewSessionId);
            const stats = report.verification_stats || status.verification_stats || null;
            setReviewReport(report.report_markdown);
            setVerificationStats(stats);
            setReviewStatus('completed');
            onCompletedRef.current?.(reviewSessionId, report.report_markdown, stats ?? undefined);
          } catch (err) {
            console.error('Failed to fetch review report:', err);
            setReviewStatus('failed');
            setReviewProgress('Analysis done but failed to fetch report');
            onFailedRef.current?.('Failed to fetch report');
          }
          if (autoResetDelay > 0) {
            setTimeout(() => {
              setReviewStatus('idle');
              setReviewSessionId(null);
              setReviewProgress('');
            }, autoResetDelay);
          }
        } else if (status.status === 'failed') {
          clearInterval(pollInterval);
          const errorMsg = status.error || 'Analysis failed';
          setReviewStatus('failed');
          setReviewProgress(errorMsg);
          onFailedRef.current?.(errorMsg);
          if (autoResetDelay > 0) {
            setTimeout(() => {
              setReviewStatus('idle');
              setReviewSessionId(null);
              setReviewProgress('');
            }, autoResetDelay);
          }
        }
      } catch (error) {
        console.error('Status poll error:', error);
      }
    }, 3000);

    return () => clearInterval(pollInterval);
  }, [reviewSessionId, reviewStatus, autoResetDelay]);

  return {
    reviewSessionId,
    reviewStatus,
    reviewProgress,
    reviewReport,
    verificationStats,
    startReview,
    resetReview,
  };
}
