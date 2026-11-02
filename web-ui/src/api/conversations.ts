import { api, API_BASE_URL } from './base';
import type { Conversation, ConversationSummary, TurnBlock } from '../types';

export interface CreatedConversation {
  id: string;
  title: string;
  turn_id: string;
}

export interface TurnStatusEvent {
  status: string;
  stage?: 'analyze' | 'search' | 'graph' | 'answer' | string;
}

export interface TurnDoneEvent {
  turn_id: string;
  intent: string | null;
  latency_ms?: number;
  /** The conversation's new title when this turn changed it; null when unchanged. */
  title?: string | null;
}

export interface TurnStreamHandlers {
  onStatus: (event: TurnStatusEvent) => void;
  onBlock: (block: TurnBlock) => void;
  onDelta: (text: string) => void;
  onDone: (event: TurnDoneEvent) => void;
  /**
   * `saved` is false when the request failed before the server took the turn
   * (network, HTTP error): a message sent with it was never stored.
   */
  onError: (message: string, saved: boolean) => void;
}

export const createConversation = async (message: string): Promise<CreatedConversation> => {
  const response = await api.post<CreatedConversation>('/api/conversations', { message });
  return response.data;
};

export const fetchMyConversations = async (
  limit = 20,
  signal?: AbortSignal,
): Promise<ConversationSummary[]> => {
  const response = await api.get<ConversationSummary[]>('/api/me/conversations', { params: { limit }, signal });
  return Array.isArray(response.data) ? response.data : [];
};

export const fetchConversation = async (id: string, signal?: AbortSignal): Promise<Conversation> => {
  const response = await api.get<Conversation>(`/api/conversations/${encodeURIComponent(id)}`, { signal });
  return response.data;
};

export const archiveConversation = async (id: string): Promise<{ ok: boolean }> => {
  const response = await api.post<{ ok: boolean }>(`/api/conversations/${encodeURIComponent(id)}/archive`);
  return response.data;
};

const HTTP_ERROR: Record<number, string> = {
  400: '지금은 이 요청을 처리할 수 없어요. 잠시 후 다시 시도해 주세요.',
  401: '로그인이 만료됐어요. 다시 로그인해 주세요.',
  404: '대화를 찾을 수 없어요.',
  429: '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.',
};

/**
 * Runs (or continues) the assistant turn and streams its events.
 * Exactly one of onDone/onError fires, unless the caller aborts — then none.
 * `message: null` runs the pending user turn (the one createConversation saved),
 * or re-runs the last turn whose answer ended in `error`.
 */
export const streamTurn = async (
  id: string,
  message: string | null,
  handlers: TurnStreamHandlers,
  signal?: AbortSignal,
): Promise<void> => {
  let finished = false;
  const finish = (fire: () => void) => {
    if (finished || signal?.aborted) return;
    finished = true;
    fire();
  };
  const fail = (text: string, saved = true) => finish(() => handlers.onError(text, saved));

  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(id)}/turns`, {
      method: 'POST',
      headers,
      body: JSON.stringify(message === null ? {} : { message }),
      signal,
    });
  } catch {
    fail('서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.', false);
    return;
  }

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('username');
      localStorage.removeItem('user_role');
      window.dispatchEvent(new Event('auth:logout'));
    }
    // FastAPI explains 400s (already answered, turn still running) in `detail`; prefer it.
    const detail = response.status === 400
      ? await response.json().then(
        (body: { detail?: unknown }) => (typeof body?.detail === 'string' ? body.detail : null),
        () => null,
      )
      : null;
    fail(detail || HTTP_ERROR[response.status] || `응답을 받지 못했어요 (HTTP ${response.status}).`, false);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    fail('응답 본문이 비어 있어요.', false);
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';
  const handleLine = (line: string) => {
    // ": keepalive" comments and blank separators carry nothing.
    if (!line.startsWith('data:')) return;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(line.slice(5).trim());
    } catch {
      return;
    }
    if (typeof data.error === 'string') fail(data.error);
    else if (data.done && typeof data.done === 'object') finish(() => handlers.onDone(data.done as TurnDoneEvent));
    else if (data.block && typeof data.block === 'object') handlers.onBlock(data.block as TurnBlock);
    else if (typeof data.delta === 'string') handlers.onDelta(data.delta);
    else if (typeof data.status === 'string') handlers.onStatus(data as unknown as TurnStatusEvent);
  };

  try {
    while (!finished) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      lines.forEach(handleLine);
    }
    if (buffer) handleLine(buffer);
  } catch {
    fail('응답이 중간에 끊겼어요. 다시 시도해 주세요.');
    return;
  } finally {
    reader.releaseLock();
  }
  fail('응답이 끝나지 않고 종료됐어요. 다시 시도해 주세요.');
};
