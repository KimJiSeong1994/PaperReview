const HANGUL_SYLLABLE = /[가-힣]/;

/**
 * Avatar initials for the sidebar account card: a Korean name keeps its first
 * syllable ("한지성" → "한"); otherwise the first two letters or digits,
 * uppercased ("home_demo" → "HO").
 */
export function userInitials(name: string): string {
  const chars = Array.from(name.trim()).filter(char => /[\p{L}\p{N}]/u.test(char));
  if (chars.length === 0) return '?';
  if (HANGUL_SYLLABLE.test(chars[0])) return chars[0];
  return chars.slice(0, 2).join('').toUpperCase();
}
