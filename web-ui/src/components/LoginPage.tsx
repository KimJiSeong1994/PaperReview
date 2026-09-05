import { useState, useEffect, useRef, type FormEvent } from 'react';
import axios from 'axios';
import { login, register } from '../api/client';
import { trackLoginEvent, trackSignUpEvent } from '../analytics/events';
import './LoginPage.css';

interface LoginModalProps {
  onLoginSuccess: () => void;
  onClose: () => void;
}

type Mode = 'signin' | 'signup';

export default function LoginModal({ onLoginSuccess, onClose }: LoginModalProps) {
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

  // Keep Tab inside the dialog, and hand focus back to whatever opened it.
  //
  // Initial focus is already handled: both forms autoFocus their first field.
  // What was missing is the other half — Tab walked straight out of the card
  // into the page behind it, and closing dropped focus on <body>, so a keyboard
  // user landed at the top of the document with no idea where they were.
  const cardRef = useRef<HTMLDivElement>(null);

  // Captured during the first render, not in the effect below: effects run
  // after the DOM commit, by which point autoFocus has already moved focus
  // into this dialog and document.activeElement is the ID field, not whatever
  // the user was on. Lazy ref init is the standard shape for this and is
  // idempotent, so it is safe during render.
  const openerRef = useRef<HTMLElement | null>(null);
  if (openerRef.current === null) {
    openerRef.current = document.activeElement as HTMLElement | null;
  }

  useEffect(() => {
    const opener = openerRef.current;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !cardRef.current) return;
      const items = cardRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
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
  }, []);

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
      setError('Please enter your ID and password.');
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
        setError('Invalid ID or password.');
      } else {
        setError('Unable to connect to the server. Please try again later.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('Please fill in all fields.');
      return;
    }
    if (username.trim().length < 3) {
      setError('Username must be at least 3 characters.');
      return;
    }
    if (password.length < 4) {
      setError('Password must be at least 4 characters.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await register(username, password);
      trackSignUpEvent();
      setSuccess('Account created! You can now sign in.');
      setPassword('');
      setConfirmPassword('');
      // Auto-switch to sign in after a short delay
      setTimeout(() => {
        setMode('signin');
        setSuccess('');
      }, 1500);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setError('Username already exists.');
      } else if (axios.isAxiosError(err) && err.response?.status === 422) {
        setError('Username: letters, numbers, underscore only (3+ chars).');
      } else {
        setError('Unable to connect to the server. Please try again later.');
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
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button className="login-close-btn" onClick={onClose} aria-label="Close">
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
            <p className="login-brand-tagline">AI-Powered Research Assistant</p>
          </div>
        </div>

        {/* Mode tabs */}
        <div className="login-tabs">
          <button
            className={`login-tab ${mode === 'signin' ? 'login-tab--active' : ''}`}
            onClick={() => switchMode('signin')}
            type="button"
          >
            Sign In
          </button>
          <button
            className={`login-tab ${mode === 'signup' ? 'login-tab--active' : ''}`}
            onClick={() => switchMode('signup')}
            type="button"
          >
            Sign Up
          </button>
        </div>

        {/* Sign In form */}
        {mode === 'signin' && (
          <form className="login-form" onSubmit={handleSignIn}>
            <div className="login-input-group">
              <label htmlFor="login-username" className="login-label">ID</label>
              <input
                id="login-username"
                type="text"
                className="login-input"
                placeholder="Enter your ID"
                value={username}
                onChange={(e) => { setUsername(e.target.value); clearForm(); }}
                autoComplete="username"
                autoFocus
                aria-invalid={!!error}
                aria-describedby={error ? 'login-error' : undefined}
              />
            </div>
            <div className="login-input-group">
              <label htmlFor="login-password" className="login-label">Password</label>
              <input
                id="login-password"
                type="password"
                className="login-input"
                placeholder="Enter your password"
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
                <span className="login-spinner" aria-label="Signing in" />
              ) : (
                'Sign In'
              )}
            </button>
          </form>
        )}

        {/* Sign Up form */}
        {mode === 'signup' && (
          <form className="login-form" onSubmit={handleSignUp}>
            <div className="login-input-group">
              <label htmlFor="reg-username" className="login-label">Username</label>
              <input
                id="reg-username"
                type="text"
                className="login-input"
                placeholder="Letters, numbers, underscore"
                value={username}
                onChange={(e) => { setUsername(e.target.value); clearForm(); }}
                autoComplete="username"
                autoFocus
                aria-invalid={!!error}
              />
            </div>
            <div className="login-input-group">
              <label htmlFor="reg-password" className="login-label">Password</label>
              <input
                id="reg-password"
                type="password"
                className="login-input"
                placeholder="At least 4 characters"
                value={password}
                onChange={(e) => { setPassword(e.target.value); clearForm(); }}
                autoComplete="new-password"
              />
            </div>
            <div className="login-input-group">
              <label htmlFor="reg-confirm" className="login-label">Confirm Password</label>
              <input
                id="reg-confirm"
                type="password"
                className="login-input"
                placeholder="Re-enter your password"
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
                'Create Account'
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
