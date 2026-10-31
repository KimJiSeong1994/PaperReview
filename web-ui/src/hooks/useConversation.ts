import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchConversation, streamTurn } from '../api/conversations';
import type { Conversation, ConversationTurn } from '../types';

/** A turn as the page shows it: server fields plus what only this tab knows. */
export interface ViewTurn extends ConversationTurn {
  /** Why the live run failed, in the reader's words. */
  error?: string;
  /** The reader pressed stop. */
  stopped?: boolean;
  /** The question this failed run sent but the server never stored; retry re-sends it. */
  retryMessage?: string;
}

export interface ConversationState {
  conversation: Conversation | null;
  turns: ViewTurn[];
  loadError: string | null;
  streaming: boolean;
  /** Latest status line of the running turn. */
  liveStatus: string | null;
  send: (message: string) => void;
  stop: () => void;
  retry: () => void;
  reload: () => void;
}

const LIVE_ID = 'live';

const localTurn = (role: ViewTurn['role'], content: string, seq: number): ViewTurn => ({
  id: role === 'assistant' ? LIVE_ID : `local-${seq}`,
  seq,
  role,
  content,
  blocks: [],
  intent: null,
  status: role === 'assistant' ? 'running' : 'done',
  created_at: new Date().toISOString(),
});

/**
 * Loads a conversation and runs its turns over SSE. Mount with a `key` per
 * conversation id: the hook never resets itself when `id` changes.
 */
export function useConversation(id: string, runOnLoad: boolean): ConversationState {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [turns, setTurns] = useState<ViewTurn[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  const [loadKey, setLoadKey] = useState(0);
  const streamRef = useRef<AbortController | null>(null);
  // One-shot: consumed by the first load that lands. A later re-run of the load
  // effect (fast refresh, reload) must never post a second bare run.
  const pendingRunRef = useRef(runOnLoad);

  const patchLive = useCallback((patch: (turn: ViewTurn) => ViewTurn) => {
    setTurns(prev => prev.map(turn => (turn.id === LIVE_ID ? patch(turn) : turn)));
  }, []);

  const run = useCallback((message: string | null) => {
    streamRef.current?.abort();
    const controller = new AbortController();
    streamRef.current = controller;
    setStreaming(true);
    setLiveStatus(null);
    setTurns(prev => {
      const seq = (prev.at(-1)?.seq ?? 0) + 1;
      // A bare re-run replaces the failed answer it retries.
      const next = message === null
        ? prev.filter((turn, index) => !(index === prev.length - 1 && turn.role === 'assistant' && turn.status === 'error'))
        : [...prev, localTurn('user', message, seq)];
      return [...next, localTurn('assistant', '', seq + 1)];
    });
    const settle = () => {
      if (streamRef.current === controller) streamRef.current = null;
      setStreaming(false);
      setLiveStatus(null);
    };
    void streamTurn(id, message, {
      onStatus: event => setLiveStatus(event.status),
      onBlock: block => patchLive(turn => ({ ...turn, blocks: [...turn.blocks, block] })),
      onDelta: text => patchLive(turn => ({ ...turn, content: turn.content + text })),
      onDone: done => {
        patchLive(turn => ({ ...turn, id: done.turn_id || `done-${turn.seq}`, intent: done.intent, status: 'done' }));
        settle();
      },
      onError: (text, saved) => {
        const retryMessage = !saved && message !== null ? message : undefined;
        patchLive(turn => ({ ...turn, id: `error-${turn.seq}`, status: 'error', error: text, retryMessage }));
        settle();
      },
    }, controller.signal);
  }, [id, patchLive]);

  useEffect(() => {
    const controller = new AbortController();
    fetchConversation(id, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return;
        setConversation(data);
        setLoadError(null);
        // A refetch during a live stream would drop the turn being written.
        if (streamRef.current) return;
        setTurns(data.turns ?? []);
        if (pendingRunRef.current) {
          pendingRunRef.current = false;
          run(null);
        }
      })
      .catch(error => {
        if (controller.signal.aborted) return;
        const status = (error as { response?: { status?: number } })?.response?.status;
        setLoadError(status === 404 ? '대화를 찾을 수 없어요. 삭제됐거나 다른 계정의 대화일 수 있어요.' : '대화를 불러오지 못했어요.');
      });
    return () => controller.abort();
  }, [id, loadKey, run]);

  // Leaving the page drops the stream; the server still finishes and saves the turn.
  useEffect(() => () => streamRef.current?.abort(), []);

  const send = useCallback((message: string) => {
    const trimmed = message.trim();
    if (trimmed && !streamRef.current) run(trimmed);
  }, [run]);

  const stop = useCallback(() => {
    if (!streamRef.current) return;
    streamRef.current.abort();
    streamRef.current = null;
    patchLive(turn => ({ ...turn, id: `stopped-${turn.seq}`, status: 'done', stopped: true }));
    setStreaming(false);
    setLiveStatus(null);
  }, [patchLive]);

  // A stream-level error was saved, so the server re-runs it on a bare post. A
  // request that failed before the server took it re-sends its question instead.
  const retry = useCallback(() => {
    if (streamRef.current) return;
    const retryMessage = turns.at(-1)?.retryMessage;
    if (retryMessage === undefined) {
      run(null);
      return;
    }
    // Drop the unsaved question and its error; run() adds the question back.
    setTurns(prev => prev.slice(0, -2));
    run(retryMessage);
  }, [run, turns]);

  const reload = useCallback(() => setLoadKey(key => key + 1), []);

  return { conversation, turns, loadError, streaming, liveStatus, send, stop, retry, reload };
}
