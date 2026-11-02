import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { createConversation } from '../../api/conversations';
import { fetchSampleConversation, fetchSampleConversations } from '../../api/samples';
import type { ViewTurn } from '../../hooks/useConversation';
import type { Conversation, SampleConversation, SampleSummary } from '../../types';
import { ConversationView } from './ConversationPage';

interface SampleConversationPageProps {
  slug: string;
}

const noop = () => {};

/**
 * A read-only sample conversation, open to guests: the same thread and
 * artifact panel as a live conversation, with a sign-in call to action in
 * place of the composer. Mount with `key={slug}`.
 */
function SampleConversationPage({ slug }: SampleConversationPageProps) {
  const navigate = useNavigate();
  const { isAuthenticated, showLoginModal, setShowLoginModal } = useAuth();
  const [sample, setSample] = useState<SampleConversation | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadKey, setLoadKey] = useState(0);
  const [others, setOthers] = useState<SampleSummary[]>([]);
  const [question, setQuestion] = useState('');
  const [startError, setStartError] = useState<string | null>(null);
  // Set by "로그인하고 이어서 물어보기" while the login dialog is open; consumed once signed in.
  const pendingRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchSampleConversation(slug, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return;
        setSample(data);
        setLoadError(null);
      })
      .catch(error => {
        if (controller.signal.aborted) return;
        const status = (error as { response?: { status?: number } })?.response?.status;
        setLoadError(status === 404 ? '이 상담 예시를 찾을 수 없어요.' : '상담 예시를 불러오지 못했어요.');
      });
    return () => controller.abort();
  }, [slug, loadKey]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSampleConversations(controller.signal)
      .then(list => {
        if (controller.signal.aborted) return;
        setOthers(list.filter(item => item.slug !== slug));
        setQuestion(list.find(item => item.slug === slug)?.question ?? '');
      })
      .catch(() => { /* the other-samples links simply do not show */ });
    return () => controller.abort();
  }, [slug]);

  const conversation = useMemo<Conversation | null>(() => (sample ? {
    id: sample.id,
    title: `${sample.title} · 상담 예시 · ${sample.asof} 기준`,
    created_at: sample.asof,
    updated_at: sample.asof,
    turns: [],
  } : null), [sample]);

  const turns = useMemo<ViewTurn[]>(() => (sample?.turns ?? []).map(turn => ({
    ...turn,
    id: `sample-${turn.seq}`,
    status: 'done',
    created_at: sample?.asof ?? '',
  })), [sample]);

  // The question to continue with: the sample's own, else its first user turn.
  const continueWith = sample?.question || question || sample?.turns.find(turn => turn.role === 'user')?.content || '';

  const startConversation = () => {
    if (!continueWith) return;
    setStartError(null);
    createConversation(continueWith)
      .then(created => navigate(`/c/${created.id}`, { state: { run: true } }))
      .catch(() => setStartError('대화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요.'));
  };

  const continueAsking = () => {
    if (isAuthenticated) {
      startConversation();
      return;
    }
    pendingRef.current = true;
    setShowLoginModal(true);
  };

  // Signed in from the dialog: ask the sample's question as a new conversation.
  useEffect(() => {
    if (!isAuthenticated || !pendingRef.current) return;
    pendingRef.current = false;
    startConversation();
  // startConversation is recreated every render; the ref gates the replay.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated]);

  // Closing the dialog without signing in drops the request.
  useEffect(() => {
    if (!showLoginModal && !isAuthenticated) pendingRef.current = false;
  }, [showLoginModal, isAuthenticated]);

  return (
    <ConversationView
      id={`sample-${slug}`}
      conversation={conversation}
      turns={turns}
      loadError={loadError}
      streaming={false}
      liveStatus={null}
      retry={noop}
      reload={() => { setLoadError(null); setLoadKey(key => key + 1); }}
      navState={{}}
      footer={(
        <div className="conv-sample-cta">
          <p className="conv-sample-cta-text">
            상담 예시예요. 로그인하면 같은 질문으로 직접 물어보고, 대화가 저장돼요.
          </p>
          <button type="button" className="home-btn" onClick={continueAsking} disabled={!continueWith}>
            로그인하고 이어서 물어보기
          </button>
          {startError && <p className="conv-error-text" role="alert">{startError}</p>}
          {others.length > 0 && (
            <nav className="conv-sample-others" aria-label="다른 샘플 보기">
              <span>다른 샘플 보기</span>
              {others.map(item => (
                <Link key={item.slug} to={`/samples/${item.slug}`}>{item.question}</Link>
              ))}
            </nav>
          )}
        </div>
      )}
    />
  );
}

export default SampleConversationPage;
