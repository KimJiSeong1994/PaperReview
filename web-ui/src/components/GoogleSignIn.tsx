import { useEffect, useRef, useState, type FormEvent } from 'react';
import axios from 'axios';
import { createGoogleChallenge, loginWithGoogle, type AuthSession, type GoogleChallenge } from '../api/auth';
import { trackLoginEvent, trackSignUpEvent } from '../analytics/events';

interface GoogleIdentity {
  initialize: (options: {
    client_id: string; nonce: string; auto_select: boolean;
    callback: (response: { credential: string }) => void;
  }) => void;
  renderButton: (container: HTMLElement, options: {
    type: 'standard'; theme: 'outline'; size: 'large'; text: 'continue_with'; locale: 'ko'; width: number;
  }) => void;
}

declare global {
  interface Window { google?: { accounts: { id: GoogleIdentity } } }
}

let sdkPromise: Promise<GoogleIdentity> | null = null;
const SCRIPT_ID = 'google-identity-client';

function loadGoogleIdentity(): Promise<GoogleIdentity> {
  if (window.google?.accounts.id) return Promise.resolve(window.google.accounts.id);
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise<GoogleIdentity>((resolve, reject) => {
    document.getElementById(SCRIPT_ID)?.remove();
    const script = document.createElement('script');
    script.id = SCRIPT_ID;
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    let settled = false;
    const finish = (sdk?: GoogleIdentity) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      script.onload = null;
      script.onerror = null;
      if (sdk) resolve(sdk);
      else {
        script.remove();
        reject(new Error('google_script_unavailable'));
      }
    };
    const timer = window.setTimeout(() => finish(), 15_000);
    script.onload = () => finish(window.google?.accounts.id);
    script.onerror = () => finish();
    document.head.appendChild(script);
  }).then((sdk) => {
    sdkPromise = null;
    return sdk;
  }, (error) => {
    sdkPromise = null;
    throw error;
  });
  return sdkPromise;
}

function errorMessage(error: unknown, linking = false): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    if (status === 429) return '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.';
    if (status === 409 && detail === 'google_account_already_linked') {
      return '기존 계정에 이미 Google 계정이 연결돼 있습니다. 연결한 Google 계정으로 로그인해주세요.';
    }
    if (status === 409) return '이 Google 계정은 다른 집현전 계정에 연결되어 있습니다. 연결된 계정으로 로그인해주세요.';
    if (status === 401) return linking
      ? '아이디 또는 비밀번호가 올바르지 않습니다.'
      : 'Google 인증이 만료되었거나 확인되지 않았습니다. 다시 시도해주세요.';
    if (status === 403) return '현재 주소에서는 Google 로그인을 사용할 수 없습니다.';
  }
  return 'Google 로그인에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.';
}

/** One browser challenge owns exactly one button/callback lifetime. */
function GoogleAttempt({ challenge, onSuccess, onFailure, onRetry }: {
  challenge?: GoogleChallenge;
  onSuccess: (session: AuthSession) => void;
  onFailure: (message: string) => void;
  onRetry: () => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<'loading' | 'ready' | 'submitting' | 'error'>('loading');
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let submitting = false;
    queueMicrotask(() => {
      if (disposed) return;
      Promise.all([
      challenge ? Promise.resolve(challenge) : createGoogleChallenge(undefined, controller.signal),
      loadGoogleIdentity(),
    ]).then(([current, sdk]) => {
      if (disposed || !container.current) return;
      if (!current.client_id || !current.nonce) throw new Error('google_challenge_unavailable');
      sdk.initialize({
        client_id: current.client_id, nonce: current.nonce, auto_select: false,
        callback: async ({ credential }) => {
          if (disposed || submitting || !credential) return;
          submitting = true;
          setPhase('submitting');
          try {
            const session = await loginWithGoogle(credential, controller.signal);
            if (!disposed) onSuccess(session);
          } catch (failure) {
            if (!disposed) onFailure(errorMessage(failure));
          }
        },
      });
      const width = Math.max(200, Math.min(320, container.current.parentElement?.clientWidth || 320));
      container.current.replaceChildren();
      sdk.renderButton(container.current, { type: 'standard', theme: 'outline', size: 'large', text: 'continue_with', locale: 'ko', width });
      setPhase('ready');
    }).catch((failure) => {
      if (disposed) return;
      setError(failure instanceof Error && failure.message === 'google_script_unavailable'
        ? 'Google 로그인 버튼을 불러오지 못했습니다. 네트워크나 콘텐츠 차단 설정을 확인해주세요.'
        : errorMessage(failure));
      setPhase('error');
    });
    });
    return () => { disposed = true; controller.abort(); };
  }, [challenge, onSuccess, onFailure]);

  return <div className="google-signin-attempt" aria-busy={phase === 'loading' || phase === 'submitting'}>
    {phase === 'loading' && <p className="login-provider-status" role="status">Google 로그인을 준비하고 있습니다.</p>}
    {phase === 'submitting' && <p className="login-provider-status" role="status">로그인 정보를 확인하고 있습니다.</p>}
    <div ref={container} className="google-signin-button" style={{ display: phase === 'ready' ? 'flex' : 'none' }} />
    {phase === 'error' && <>
      <p className="login-error" role="alert">{error}</p>
      <button type="button" className="login-submit-btn" onClick={onRetry}>다시 시도</button>
    </>}
  </div>;
}

export default function GoogleSignIn({ onLoginSuccess }: { onLoginSuccess: () => void }) {
  const [linking, setLinking] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [challenge, setChallenge] = useState<GoogleChallenge>();
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(true);
  const proofRequest = useRef<AbortController | null>(null);
  const successCallback = useRef(onLoginSuccess);
  useEffect(() => { successCallback.current = onLoginSuccess; }, [onLoginSuccess]);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; proofRequest.current?.abort(); };
  }, []);

  // Stable callbacks keep GIS initialization bound to a nonce, not every rerender.
  const [onSuccess] = useState(() => (session: AuthSession) => {
    if (!active.current) return;
    localStorage.setItem('username', session.username);
    localStorage.setItem('user_role', session.role || 'user');
    localStorage.setItem('access_token', session.access_token);
    if (session.is_new_user) trackSignUpEvent();
    trackLoginEvent();
    successCallback.current();
  });
  const [onFailure] = useState(() => (message: string) => {
    if (!active.current) return;
    setError(message);
    setChallenge(undefined);
    setAttempt((value) => value + 1);
  });

  const resetAttempt = () => {
    setError('');
    setChallenge(undefined);
    setAttempt((value) => value + 1);
  };
  const switchMode = () => {
    proofRequest.current?.abort();
    setBusy(false);
    setLinking((value) => !value);
    setPassword('');
    resetAttempt();
  };
  const proveAccount = async (event: FormEvent) => {
    event.preventDefault();
    if (proofRequest.current && !proofRequest.current.signal.aborted) return;
    if (!username.trim() || !password) {
      setError('기존 아이디와 비밀번호를 입력해주세요.');
      return;
    }
    const controller = new AbortController();
    proofRequest.current = controller;
    setBusy(true);
    setError('');
    try {
      const next = await createGoogleChallenge({ username: username.trim(), password }, controller.signal);
      if (!active.current || controller.signal.aborted) return;
      setPassword('');
      setChallenge(next);
    } catch (failure) {
      if (active.current && !controller.signal.aborted) setError(errorMessage(failure, true));
    } finally {
      if (proofRequest.current === controller) proofRequest.current = null;
      if (active.current && !controller.signal.aborted) setBusy(false);
    }
  };

  return <div className="google-signin">
    <div className="google-signin-intro">
      <h3>{linking ? '기존 계정 연결' : 'Google 계정으로 시작하기'}</h3>
      <p>{linking ? '기존 계정을 한 번 확인한 뒤 Google 계정을 연결합니다. 저장한 데이터와 권한은 그대로 유지됩니다.'
        : '처음 이용하면 Google 계정으로 가입됩니다. 기존 아이디가 있다면 먼저 아래의 계정 연결을 선택해주세요.'}</p>
    </div>
    {error && <p className="login-error" role="alert">{error}</p>}
    {linking && !challenge ? <form className="login-form" onSubmit={proveAccount}>
      <div className="login-input-group">
        <label htmlFor="google-link-username" className="login-label">기존 아이디</label>
        <input id="google-link-username" className="login-input" autoComplete="username" autoFocus
          value={username} onChange={(event) => setUsername(event.target.value)} disabled={busy} />
      </div>
      <div className="login-input-group">
        <label htmlFor="google-link-password" className="login-label">기존 비밀번호</label>
        <input id="google-link-password" className="login-input" type="password" autoComplete="current-password"
          value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} />
      </div>
      <button className="login-submit-btn" type="submit" disabled={busy}>{busy ? '기존 계정 확인 중…' : '기존 계정 확인'}</button>
    </form> : <>
      {linking && <p className="login-success" role="status">기존 계정을 확인했습니다. 연결할 Google 계정을 선택해주세요.</p>}
      <GoogleAttempt key={`${linking}-${attempt}`} challenge={challenge} onSuccess={onSuccess} onFailure={onFailure} onRetry={resetAttempt} />
    </>}
    <button type="button" className="google-link-switch" onClick={switchMode}>
      {linking ? 'Google 로그인으로 돌아가기' : '기존 계정 연결'}
    </button>
  </div>;
}
