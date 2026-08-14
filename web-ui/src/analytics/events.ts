import { trackEvent, type AnalyticsEventName, type AnalyticsEventParams } from './ga4';

type SearchSource = 'home' | 'fixed_bar' | 'url_prefill';
type SearchStatus = 'success' | 'empty' | 'error' | 'non_academic';

function bucketCount(count: number): string {
  if (count <= 0) return '0';
  if (count <= 5) return '1-5';
  if (count <= 20) return '6-20';
  if (count <= 50) return '21-50';
  return '51+';
}

function bucketQueryLength(query: string): string {
  const length = query.trim().length;
  if (length <= 10) return '1-10';
  if (length <= 30) return '11-30';
  if (length <= 80) return '31-80';
  return '81+';
}

function classifyQuery(query: string): string {
  const trimmed = query.trim();
  if ([...trimmed].every((char) => char.charCodeAt(0) <= 0x7f)) return 'latin';
  if (/[가-힣]/.test(trimmed)) return 'korean';
  return 'mixed_or_other';
}

function sendAllowedEvent(eventName: AnalyticsEventName, params?: AnalyticsEventParams): void {
  trackEvent(eventName, params);
}

/**
 * Ties one search impression to the clicks it earns.
 *
 * `search_id` is random per search and encodes nothing about the query — it
 * only lets a later `paper_select` be joined back to the result set it came
 * from, which is what MRR and CTR are computed from. Deliberately not a hash
 * of the query: a 48-bit hash of a common academic search is reversible by
 * dictionary, and this channel promises not to carry search text.
 */
export interface SearchImpression {
  searchId: string;
  /** Ranking variant that ordered the results, echoed by the API. */
  rankingVariant?: string;
}

export function trackSearchEvent(
  query: string,
  resultStatus: SearchStatus,
  resultCount: number,
  source: SearchSource,
  impression?: SearchImpression,
): void {
  if (!query.trim()) return;
  sendAllowedEvent('search', {
    query_length_bucket: bucketQueryLength(query),
    query_class: classifyQuery(query),
    result_status: resultStatus,
    result_count_bucket: bucketCount(resultCount),
    source,
    ...(impression?.searchId ? { search_id: impression.searchId } : {}),
    ...(impression?.rankingVariant ? { ranking_variant: impression.rankingVariant } : {}),
  });
}

export function trackLoginEvent(): void {
  sendAllowedEvent('login');
}

export function trackSignUpEvent(): void {
  sendAllowedEvent('sign_up');
}

export function trackDeepReviewStart(selectedCount: number): void {
  sendAllowedEvent('deep_review_start', { selected_count_bucket: bucketCount(selectedCount) });
}

export function trackDeepReviewComplete(selectedCount: number): void {
  sendAllowedEvent('deep_review_complete', { selected_count_bucket: bucketCount(selectedCount) });
}

export function trackDeepReviewFail(selectedCount: number): void {
  sendAllowedEvent('deep_review_fail', { selected_count_bucket: bucketCount(selectedCount) });
}

export function trackPaperSelect(
  source: 'list' | 'graph',
  impression?: SearchImpression & { rank?: number },
): void {
  sendAllowedEvent('paper_select', {
    source,
    ...(impression?.searchId ? { search_id: impression.searchId } : {}),
    // 1-based position in the ranked list. Paired with the impression's
    // result count this is everything MRR@k and CTR@k need.
    ...(impression?.rank && impression.rank > 0 ? { rank: impression.rank } : {}),
  });
}

export function trackBookmarkSave(): void {
  sendAllowedEvent('bookmark_save');
}

export function trackReportDownload(): void {
  sendAllowedEvent('report_download');
}

export function trackPosterGenerateStart(): void {
  sendAllowedEvent('poster_generate_start');
}

export function trackPosterGenerateComplete(status: string = 'succeeded'): void {
  sendAllowedEvent('poster_generate_complete', { status });
}

export function trackPosterGenerateFail(status: string = 'failed'): void {
  sendAllowedEvent('poster_generate_fail', { status });
}
