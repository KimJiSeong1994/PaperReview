import { useState, useEffect, useRef, type FormEvent } from 'react';
import axios from 'axios';
import { getAuthConfig, login, register, type AuthConfig } from '../api/client';
import GoogleSignIn from './GoogleSignIn';
import { trackLoginEvent, trackSignUpEvent } from '../analytics/events';
import './LoginPage.css';

interface LoginModalProps {
  onLoginSuccess: () => void;
  onClose: () => void;
}

type Mode = 'signin' | 'signup';

export default function LoginModal({ onLoginSuccess, onClose }: LoginModalProps) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [configError, setConfigError] = useState(false);
  const [configAttempt, setConfigAttempt] = useState(0);
  const [mode, setMode] = useState<Mode>('signin');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Prevent body scroll when modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  const cardRef = useRef<HTMLDivElement>(null);
  // Capture before asynchronous provider loading moves focus into the dialog.
  const [opener] = useState(() => document.activeElement as HTMLElement | null);
  useEffect(() => { cardRef.current?.focus(); }, []);

  useEffect(() => {
    const controller = new AbortController();
    getAuthConfig(controller.signal)
      .then((value) => { if (!controller.signal.aborted) setConfig(value); })
      .catch(() => { if (!controller.signal.aborted) setConfigError(true); });
    return () => controller.abort();
  }, [configAttempt]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !cardRef.current) return;
      const items = cardRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select, textarea, iframe, [tabindex]:not([tabindex="-1"])',
      );
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const inside = cardRef.current.contains(active);
      if (event.shiftKey && (active === first || !inside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !inside)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      opener?.focus?.();
    };
  }, [opener]);

  const clearForm = () => {
    setError('');
    setSuccess('');
  };

  const switchMode = (newMode: Mode) => {
    setMode(newMode);
    setError('');
    setSuccess('');
    setUsername('');
    setPassword('');
    setConfirmPassword('');
  };

  const handleSignIn = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('아이디와 비밀번호를 입력해주세요.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const response = await login(username, password);
      localStorage.setItem('access_token', response.access_token);
      localStorage.setItem('username', response.username);
      localStorage.setItem('user_role', response.role || 'user');
      trackLoginEvent();
      onLoginSuccess();
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        setError('아이디 또는 비밀번호가 올바르지 않습니다.');
      } else {
        setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('모든 항목을 입력해주세요.');
      return;
    }
    if (username.trim().length < 3) {
      setError('아이디는 3자 이상이어야 합니다.');
      return;
    }
    if (password.length < 4) {
      setError('비밀번호는 4자 이상이어야 합니다.');
      return;
    }
    if (password !== confirmPassword) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await register(username, password);
      trackSignUpEvent();
      setSuccess('계정이 만들어졌습니다. 이제 로그인할 수 있습니다.');
      setPassword('');
      setConfirmPassword('');
      // Auto-switch to sign in after a short delay
      setTimeout(() => {
        setMode('signin');
        setSuccess('');
      }, 1500);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setError('이미 사용 중인 아이디입니다.');
      } else if (axios.isAxiosError(err) && err.response?.status === 422) {
        setError('아이디는 영문, 숫자, 밑줄만 쓸 수 있습니다 (3자 이상).');
      } else {
        setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-overlay" onClick={onClose}>
      <div
        className="login-card"
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-dialog-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button className="login-close-btn" onClick={onClose} aria-label="닫기">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        {/* Brand header */}
        <div className="login-brand">
          <picture>
            <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
            <img
              src="/Jiphyeonjeon_llama.png"
              alt="Jiphyeonjeon"
              className="login-logo"
              width={128}
              height={128}
              loading="eager"
              fetchPriority="high"
            />
          </picture>
          <div className="login-brand-text">
            <h2 id="login-dialog-title" className="login-brand-name">Jiphyeonjeon</h2>
            <p className="login-brand-tagline">AI 논문 검색·리뷰 도구</p>
          </div>
        </div>

        {!config && <div className="login-provider-loading">
          {configError ? <>
            <p className="login-error" role="alert">로그인 설정을 불러오지 못했습니다. 다시 시도해주세요.</p>
            <button type="button" className="login-submit-btn" onClick={() => { setConfigError(false); setConfigAttempt((value) => value + 1); }}>다시 시도</button>
          </> : <p className="login-provider-status" role="status">로그인 방식을 확인하고 있습니다.</p>}
        </div>}
        {config?.google_enabled && <GoogleSignIn onLoginSuccess={onLoginSuccess} />}
        {config && !config.google_enabled && config.password_login_enabled && <>
        {/* Mode tabs */}
        <div className="login-tabs">
          <button
            className={`login-tab ${mode === 'signin' ? 'login-tab--active' : ''}`}
            onClick={() => switchMode('signin')}
            type="button"
          >
            로그인
          </button>
          {config.registration_enabled && <button
            className={`login-tab ${mode === 'signup' ? 'login-tab--active' : ''}`}
            onClick={() => switchMode('signup')}
            type="button"
          >
            회원가입
          </button>}
        </div>

        {/* Sign In form */}
        {mode === 'signin' && (
          <form className="login-form" onSubmit={handleSignIn}>
            <div className="login-input-group">
              <label htmlFor="login-username" className="login-label">아이디</label>
              <input
                id="login-username"
                type="text"
                className="login-input"
                placeholder="아이디를 입력하세요"
                value={username}
                onChange={(e) => { setUsername(e.target.value); clearForm(); }}
                autoComplete="username"
                autoFocus
                aria-invalid={!!error}
                aria-describedby={error ? 'login-error' : undefined}
              />
            </div>
            <div className="login-input-group">
              <label htmlFor="login-password" className="login-label">비밀번호</label>
              <input
                id="login-password"
                type="password"
                className="login-input"
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => { setPassword(e.target.value); clearForm(); }}
                autoComplete="current-password"
              />
            </div>
            {error && <p className="login-error" id="login-error" role="alert">{error}</p>}
            <button
              type="submit"
              className="login-submit-btn"
              disabled={loading}
            >
              {loading ? (
                <span className="login-spinner" aria-label="로그인 중" />
              ) : (
                '로그인'
              )}
            </button>
          </form>
        )}

        {/* Sign Up form */}
        {mode === 'signup' && config.registration_enabled && (
          <form className="login-form" onSubmit={handleSignUp}>
            <div className="login-input-group">
              <label htmlFor="reg-username" className="login-label">아이디</label>
              <input
                id="reg-username"
                type="text"
                className="login-input"
                placeholder="영문, 숫자, 밑줄"
                value={username}
                onChange={(e) => { setUsername(e.target.value); clearForm(); }}
                autoComplete="username"
                autoFocus
                aria-invalid={!!error}
              />
            </div>
            <div className="login-input-group">
              <label htmlFor="reg-password" className="login-label">비밀번호</label>
              <input
                id="reg-password"
                type="password"
                className="login-input"
                placeholder="4자 이상"
                value={password}
                onChange={(e) => { setPassword(e.target.value); clearForm(); }}
                autoComplete="new-password"
              />
            </div>
            <div className="login-input-group">
              <label htmlFor="reg-confirm" className="login-label">비밀번호 확인</label>
              <input
                id="reg-confirm"
                type="password"
                className="login-input"
                placeholder="비밀번호를 다시 입력하세요"
                value={confirmPassword}
                onChange={(e) => { setConfirmPassword(e.target.value); clearForm(); }}
                autoComplete="new-password"
              />
            </div>
            {error && <p className="login-error" id="login-error" role="alert">{error}</p>}
            {success && <p className="login-success" role="status">{success}</p>}
            <button
              type="submit"
              className="login-submit-btn"
              disabled={loading}
            >
              {loading ? (
                <span className="login-spinner" aria-label="Creating account" />
              ) : (
                '계정 만들기'
              )}
            </button>
          </form>
        )}
        </>}
        {config && !config.google_enabled && !config.password_login_enabled && <p className="login-error" role="alert">로그인 서비스를 준비하고 있습니다. 잠시 후 다시 시도해주세요.</p>}
      </div>
    </div>
  );
}
