import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { streamTurn } from '../api/conversations';

const storage = new Map<string, string>();
const storageShim = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, String(value)); },
  removeItem: (key: string) => { storage.delete(key); },
  clear: () => storage.clear(),
  key: (index: number) => [...storage.keys()][index] ?? null,
  get length() { return storage.size; },
};
Object.defineProperty(globalThis, 'localStorage', { configurable: true, writable: true, value: storageShim });
Object.defineProperty(window, 'localStorage', { configurable: true, writable: true, value: storageShim });

/** A fetch response whose body yields the given chunks, split wherever the server flushed. */
function sseResponse(chunks: string[], status = 200) {
  const encoder = new TextEncoder();
  const queue = [...chunks];
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    body: {
      getReader: () => ({
        read: async () => (queue.length
          ? { done: false, value: encoder.encode(queue.shift()!) }
          : { done: true, value: undefined }),
        releaseLock: () => {},
      }),
    },
  };
}

function handlers() {
  return { onStatus: vi.fn(), onBlock: vi.fn(), onDelta: vi.fn(), onDone: vi.fn(), onError: vi.fn() };
}

describe('streamTurn', () => {
  beforeEach(() => {
    storage.clear();
    storage.set('access_token', 'tok');
  });
  afterEach(() => vi.unstubAllGlobals());

  it('parses status, blocks, deltas and done, skipping keepalive comments and split lines', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([
      'data: {"status": "검색하는 중", "stage": "search"}\n\n: keepalive\n\n',
      'data: {"block": {"type": "search_results", "query": "q", "total": 1, "query_hash": "h", "partial": false, "degraded": [], "papers": []}}\n\n',
      'data: {"delta": "첫 문장',
      '"}\n\ndata: {"delta": " [1]"}\n\n',
      'data: {"done": {"turn_id": "t2", "intent": "search", "latency_ms": 10}}\n\n',
    ]));
    vi.stubGlobal('fetch', fetchMock);
    const h = handlers();

    await streamTurn('c1', null, h);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/conversations\/c1\/turns$/);
    expect(init.body).toBe('{}');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(h.onStatus).toHaveBeenCalledWith({ status: '검색하는 중', stage: 'search' });
    expect(h.onBlock.mock.calls[0][0]).toMatchObject({ type: 'search_results', query_hash: 'h' });
    expect(h.onDelta.mock.calls.map(call => call[0])).toEqual(['첫 문장', ' [1]']);
    expect(h.onDone).toHaveBeenCalledWith({ turn_id: 't2', intent: 'search', latency_ms: 10 });
    expect(h.onError).not.toHaveBeenCalled();
  });

  it('ends on an error event and fires no second terminal callback', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'data: {"delta": "부분"}\n\ndata: {"error": "검색에 실패했어요"}\n\n',
      'data: {"done": {"turn_id": "t", "intent": "search"}}\n\n',
    ])));
    const h = handlers();
    await streamTurn('c1', '후속 질문', h);
    expect(h.onError).toHaveBeenCalledTimes(1);
    // A stream-level error means the server saved the turn.
    expect(h.onError).toHaveBeenCalledWith('검색에 실패했어요', true);
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it('reports a stream that closes without a terminal event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(['data: {"delta": "끊김"}\n\n'])));
    const h = handlers();
    await streamTurn('c1', null, h);
    expect(h.onError).toHaveBeenCalledTimes(1);
  });

  it('clears the session and signals logout on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([], 401)));
    const onLogout = vi.fn();
    window.addEventListener('auth:logout', onLogout);
    const h = handlers();
    await streamTurn('c1', null, h);
    window.removeEventListener('auth:logout', onLogout);
    expect(storage.has('access_token')).toBe(false);
    expect(onLogout).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledTimes(1);
  });

  it('shows the server detail of a 400 as the error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ...sseResponse([], 400),
      json: async () => ({ detail: '이전 답변이 아직 진행 중이에요.' }),
    }));
    const h = handlers();
    await streamTurn('c1', '또 질문', h);
    // Rejected before the server took it: the message was not saved.
    expect(h.onError).toHaveBeenCalledWith('이전 답변이 아직 진행 중이에요.', false);
  });

  it('stays silent when the caller aborts', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => {
      controller.abort();
      throw new DOMException('aborted', 'AbortError');
    }));
    const h = handlers();
    await streamTurn('c1', null, h, controller.signal);
    expect(h.onError).not.toHaveBeenCalled();
    expect(h.onDone).not.toHaveBeenCalled();
  });
});
