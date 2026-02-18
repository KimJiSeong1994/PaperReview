import type { ChatMessage, ChatSource, HighlightItem } from '../../api/client';

export const CHAT_STORAGE_KEY = 'mypage_chat_history';

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
