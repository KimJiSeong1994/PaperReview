import { API_BASE_URL } from './base';

export interface ChatSource {
  ref: number;
  id: string;
  title: string;
  num_papers: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: ChatSource[];
}

export const chatWithBookmarks = async (
  messages: ChatMessage[],
  bookmarkIds: string[],
  onChunk: (content: string) => void,
  onSources: (sources: ChatSource[]) => void,
  onDone: () => void,
  onError: (error: string) => void,
): Promise<void> => {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ messages, bookmark_ids: bookmarkIds }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('username');
    }
    onError(`HTTP ${response.status}: ${response.statusText}`);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    onError('No response body');
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          if (data.content) {
            onChunk(data.content);
          } else if (data.sources) {
            onSources(data.sources);
          } else if (data.done) {
            onDone();
            return;
          } else if (data.error) {
            onError(data.error);
            return;
          }
        } catch {
          // skip malformed lines
        }
      }
    }
  }
  onDone();
};