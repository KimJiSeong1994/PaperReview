import type { ChatMessage, ChatSource, HighlightItem } from '../../api/client';

export const CHAT_STORAGE_KEY = 'mypage_chat_history';

export const TONE_MAP: Record<string, string> = {
  finding: 'green', evidence: 'green', contribution: 'green',
  methodology: 'blue', insight: 'blue', reproducibility: 'blue',
  limitation: 'rose', gap: 'rose',
};

export function getTone(hl: HighlightItem): string {
  if (hl.category && TONE_MAP[hl.category]) return TONE_MAP[hl.category];
  if (hl.color === '#6ee7b7') return 'green';
  if (hl.color === '#93c5fd' || hl.color === '#c4b5fd') return 'blue';
  if (hl.color === '#fca5a5') return 'rose';
  return 'blue';
}

export interface Bookmark {
  id: string;
  title: string;
  session_id: string;
  query: string;
  num_papers: number;
  created_at: string;
  tags: string[];
  topic: string;
  has_notes?: boolean;
}

export type { ChatMessage, ChatSource, HighlightItem };
