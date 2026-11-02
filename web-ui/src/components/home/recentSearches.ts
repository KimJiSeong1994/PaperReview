/**
 * Per-device recent searches for the home sidebar and "이어서 하기".
 *
 * The server never stores raw queries (first-party analytics strips them), so
 * this is the only source until a user-scoped history exists.
 */
const STORAGE_PREFIX = 'jh.recentSearches';
const MAX_ITEMS = 10;

/** One list per signed-in account, so a shared browser never shows another person's queries. */
function storageKey(): string {
  try {
    const owner = localStorage.getItem('username');
    return owner ? `${STORAGE_PREFIX}:${owner}` : STORAGE_PREFIX;
  } catch {
    return STORAGE_PREFIX;
  }
}

export interface RecentSearch {
  query: string;
  at: string;
}

export function readRecentSearches(): RecentSearch[] {
  try {
    const raw = localStorage.getItem(storageKey());
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
    localStorage.setItem(storageKey(), JSON.stringify(next));
  } catch {
    // Storage can be unavailable (private mode, quota); the search still runs.
  }
}
