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

export function trackSearchEvent(
  query: string,
  resultStatus: SearchStatus,
  resultCount: number,
  source: SearchSource,
): void {
  if (!query.trim()) return;
  sendAllowedEvent('search', {
    query_length_bucket: bucketQueryLength(query),
    query_class: classifyQuery(query),
    result_status: resultStatus,
    result_count_bucket: bucketCount(resultCount),
    source,
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

export function trackBookmarkSave(): void {
  sendAllowedEvent('bookmark_save');
}

export function trackReportDownload(): void {
  sendAllowedEvent('report_download');
}

export function trackPosterGenerateStart(): void {
  sendAllowedEvent('poster_generate_start');
}

export function trackPosterGenerateComplete(): void {
  sendAllowedEvent('poster_generate_complete');
}
