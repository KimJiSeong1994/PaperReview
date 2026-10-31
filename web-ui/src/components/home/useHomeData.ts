import { useCallback, useEffect, useState } from 'react';
import { fetchBlogPosts } from '../../api/blog';
import { getBookmarks } from '../../api/bookmarks';
import { fetchCurricula } from '../../api/curriculum';
import { fetchMyReviewSessions, type ReviewSessionSummary } from '../../api/me';
import {
  fetchRecommendationNotifications,
  type RecommendationNotificationResponse,
} from '../../api/recommendations';
import type { CurriculumSummary } from '../curriculum/types';
import type { Bookmark } from '../mypage/types';

export interface HomeBlogPost {
  slug: string;
  title: string;
  updated_at?: string | null;
}

export interface HomeData {
  recommendations: RecommendationNotificationResponse | null;
  recommendationsFailed: boolean;
  bookmarks: Bookmark[];
  curricula: CurriculumSummary[];
  reviewSessions: ReviewSessionSummary[];
  posts: HomeBlogPost[];
  reloadRecommendations: () => void;
}

const asBookmarks = (raw: unknown): Bookmark[] => {
  if (Array.isArray(raw)) return raw as Bookmark[];
  const list = (raw as { bookmarks?: unknown } | null)?.bookmarks;
  return Array.isArray(list) ? (list as Bookmark[]) : [];
};

const asPosts = (raw: unknown): HomeBlogPost[] => {
  const list = Array.isArray(raw) ? raw : (raw as { posts?: unknown } | null)?.posts;
  return Array.isArray(list)
    ? list.filter((post): post is HomeBlogPost => (
      typeof post === 'object' && post !== null
      && typeof (post as HomeBlogPost).slug === 'string'
      && typeof (post as HomeBlogPost).title === 'string'
    ))
    : [];
};

/**
 * Everything the home needs beyond the search box. Each request fails on its
 * own: a missing block renders its empty state instead of hiding the page.
 */
export function useHomeData(isAuthenticated: boolean): HomeData {
  const [recommendations, setRecommendations] = useState<RecommendationNotificationResponse | null>(null);
  const [recommendationsFailed, setRecommendationsFailed] = useState(false);
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [curricula, setCurricula] = useState<CurriculumSummary[]>([]);
  const [reviewSessions, setReviewSessions] = useState<ReviewSessionSummary[]>([]);
  const [posts, setPosts] = useState<HomeBlogPost[]>([]);
  const [recommendationKey, setRecommendationKey] = useState(0);

  const reloadRecommendations = useCallback(() => setRecommendationKey(key => key + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    fetchBlogPosts(undefined, 'paper-review', 1, 2)
      .then(response => { if (!controller.signal.aborted) setPosts(asPosts(response.data)); })
      .catch(() => { /* public block stays empty */ });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const controller = new AbortController();
    getBookmarks()
      .then(raw => { if (!controller.signal.aborted) setBookmarks(asBookmarks(raw)); })
      .catch(() => { /* empty state */ });
    fetchCurricula()
      // Preset courses belong to everyone; the sidebar lists only the user's own.
      .then(response => { if (!controller.signal.aborted) setCurricula((response.curricula ?? []).filter(course => !course.is_preset)); })
      .catch(() => { /* empty state */ });
    fetchMyReviewSessions(5, controller.signal)
      .then(response => { if (!controller.signal.aborted) setReviewSessions(response.sessions ?? []); })
      .catch(() => { /* empty state */ });
    return () => controller.abort();
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const controller = new AbortController();
    fetchRecommendationNotifications(3, controller.signal)
      .then(response => {
        if (controller.signal.aborted) return;
        setRecommendations(response);
        setRecommendationsFailed(false);
      })
      .catch(() => { if (!controller.signal.aborted) setRecommendationsFailed(true); });
    return () => controller.abort();
  }, [isAuthenticated, recommendationKey]);

  // Signed-out renders never read member data, so stale values are not reset
  // here; a later sign-in refetches and replaces them.
  return {
    recommendations: isAuthenticated ? recommendations : null,
    recommendationsFailed: isAuthenticated && recommendationsFailed,
    bookmarks: isAuthenticated ? bookmarks : [],
    curricula: isAuthenticated ? curricula : [],
    reviewSessions: isAuthenticated ? reviewSessions : [],
    posts,
    reloadRecommendations,
  };
}
