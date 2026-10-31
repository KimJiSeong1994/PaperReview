/**
 * Per-device recent searches for the home sidebar and "이어서 하기".
 *
 * The server never stores raw queries (first-party analytics strips them), so
 * this is the only source until a user-scoped history exists.
 */
const STORAGE_KEY = 'jh.recentSearches';
const MAX_ITEMS = 10;

export interface RecentSearch {
  query: string;
  at: string;
}

export function readRecentSearches(): RecentSearch[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is RecentSearch => (
      typeof item === 'object' && item !== null
      && typeof (item as RecentSearch).query === 'string'
      && typeof (item as RecentSearch).at === 'string'
    ));
  } catch {
    return [];
  }
}

export function rememberRecentSearch(query: string, now = new Date()): void {
  const trimmed = query.trim();
  if (!trimmed) return;
  try {
    const rest = readRecentSearches().filter(item => item.query !== trimmed);
    const next = [{ query: trimmed, at: now.toISOString() }, ...rest].slice(0, MAX_ITEMS);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage can be unavailable (private mode, quota); the search still runs.
  }
}
