import { useEffect, useState } from 'react';
import './SoulPanel.css';
import { clearSoul, deleteSoulMemory, fetchSoul, saveSoulProfile, SOUL_PROFILE_MAX } from '../../api/soul';
import type { SoulMemory } from '../../types';

const KIND_LABEL: Record<SoulMemory['kind'], string> = {
  preference: '선호',
  topic: '관심 주제',
  paper: '논문',
  fact: '사실',
};
const KIND_ORDER: SoulMemory['kind'][] = ['preference', 'topic', 'paper', 'fact'];

/** "집현전이 기억하는 것": the profile the user writes and the memories conversations left behind. */
function SoulPanel() {
  const [loadKey, setLoadKey] = useState(0);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [memories, setMemories] = useState<SoulMemory[]>([]);
  const [savedProfile, setSavedProfile] = useState('');
  const [draft, setDraft] = useState('');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [deleting, setDeleting] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchSoul(controller.signal)
      .then(soul => {
        if (controller.signal.aborted) return;
        setMemories(soul.memories ?? []);
        setSavedProfile(soul.user_md ?? '');
        setDraft(soul.user_md ?? '');
        setLoadState('ready');
      })
      .catch(() => { if (!controller.signal.aborted) setLoadState('error'); });
    return () => controller.abort();
  }, [loadKey]);

  const reload = () => {
    setLoadState('loading');
    setLoadKey(key => key + 1);
  };

  const save = () => {
    setSaveState('saving');
    saveSoulProfile(draft)
      .then(result => {
        setSavedProfile(result.user_md);
        setDraft(result.user_md);
        setSaveState('saved');
      })
      .catch(() => setSaveState('error'));
  };

  const remove = (id: string) => {
    setDeleting(id);
    setActionError(null);
    deleteSoulMemory(id)
      .then(() => setMemories(prev => prev.filter(memory => memory.id !== id)))
      .catch(() => setActionError('기억을 지우지 못했어요. 잠시 후 다시 시도해 주세요.'))
      .finally(() => setDeleting(null));
  };

  const clearAll = () => {
    setClearing(true);
    setActionError(null);
    clearSoul()
      .then(() => {
        setConfirmClear(false);
        reload();
      })
      .catch(() => setActionError('모두 지우지 못했어요. 잠시 후 다시 시도해 주세요.'))
      .finally(() => setClearing(false));
  };

  const groups = KIND_ORDER
    .map(kind => [kind, memories.filter(memory => memory.kind === kind)] as const)
    .filter(([, items]) => items.length > 0);

  return (
    <section className="soul-panel" aria-labelledby="soul-title">
      <header className="soul-head">
        <h2 id="soul-title" className="soul-title">집현전이 기억하는 것</h2>
        <p className="soul-subtitle">대화에서 알게 된 선호·관심 주제·논문을 다음 대화에 반영합니다. 직접 고치거나 지울 수 있어요.</p>
      </header>

      {loadState === 'loading' && <p className="soul-muted" role="status">불러오는 중…</p>}
      {loadState === 'error' && (
        <div className="soul-error" role="alert">
          <span>기억을 불러오지 못했어요.</span>
          <button type="button" className="soul-btn" onClick={reload}>다시 불러오기</button>
        </div>
      )}

      {loadState === 'ready' && (
        <>
          <div className="soul-block">
            <label htmlFor="soul-profile" className="soul-label">나에 대해 알려주기</label>
            <textarea
              id="soul-profile"
              className="soul-textarea"
              rows={4}
              maxLength={SOUL_PROFILE_MAX}
              value={draft}
              placeholder="예: 그래프 기반 검색을 연구하는 대학원생이에요. 요약은 짧게, 수식은 꼭 같이 보여 주세요."
              onChange={event => {
                setDraft(event.target.value);
                if (saveState !== 'saving') setSaveState('idle');
              }}
            />
            <div className="soul-row">
              <span className="soul-muted soul-count" aria-live="polite">{draft.length}/{SOUL_PROFILE_MAX}자</span>
              {saveState === 'saved' && <span className="soul-muted" role="status">저장했어요.</span>}
              {saveState === 'error' && <span className="soul-error-text" role="alert">저장하지 못했어요.</span>}
              <button
                type="button"
                className="soul-btn soul-btn-primary"
                onClick={save}
                disabled={saveState === 'saving' || draft === savedProfile}
              >
                {saveState === 'saving' ? '저장 중…' : '저장'}
              </button>
            </div>
          </div>

          <div className="soul-block">
            <div className="soul-row soul-list-head">
              <h3 className="soul-label">기억한 내용 · {memories.length}</h3>
              {memories.length > 0 && (confirmClear ? (
                <span className="soul-confirm">
                  <span>정말 모두 지울까요?</span>
                  <button type="button" className="soul-btn soul-btn-danger" onClick={clearAll} disabled={clearing}>
                    {clearing ? '지우는 중…' : '모두 지우기 확인'}
                  </button>
                  <button type="button" className="soul-btn" onClick={() => setConfirmClear(false)} disabled={clearing}>취소</button>
                </span>
              ) : (
                <button type="button" className="soul-btn" onClick={() => setConfirmClear(true)}>모두 지우기</button>
              ))}
            </div>
            {actionError && <p className="soul-error-text" role="alert">{actionError}</p>}

            {groups.length === 0 ? (
              <p className="soul-muted">아직 기억한 것이 없어요. 대화를 나누면 여기에 쌓입니다.</p>
            ) : groups.map(([kind, items]) => (
              <section key={kind} className="soul-group" aria-label={KIND_LABEL[kind]}>
                <h4 className="soul-group-title">{KIND_LABEL[kind]} · {items.length}</h4>
                <ul className="soul-list">
                  {items.map(memory => (
                    <li key={memory.id} className="soul-item">
                      <span className="soul-item-text">{memory.text}</span>
                      <button
                        type="button"
                        className="soul-icon-btn"
                        aria-label="기억 삭제"
                        title="기억 삭제"
                        onClick={() => remove(memory.id)}
                        disabled={deleting === memory.id}
                      >
                        <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
                          <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                        </svg>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

export default SoulPanel;
