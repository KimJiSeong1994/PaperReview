import { useState, useEffect, type FormEvent } from 'react';
import axios from 'axios';
import { login } from '../api/client';
import './LoginPage.css';

interface LoginModalProps {
  onLoginSuccess: () => void;
  onClose: () => void;
}

export default function LoginModal({ onLoginSuccess, onClose }: LoginModalProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
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

  const handleSubmit = async (e: FormEvent) => {
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

  return (
    <div className="login-overlay" onClick={onClose}>
      <div className="login-card" onClick={(e) => e.stopPropagation()}>
        {/* Close button */}
        <button className="login-close-btn" onClick={onClose} aria-label="Close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        {/* Brand header */}
        <div className="login-brand">
          <img
            src="/Jipyheonjeon_llama.png"
            alt="Jipyheonjeon"
            className="login-logo"
          />
          <div className="login-brand-text">
            <h1 className="login-brand-name">Jipyheonjeon</h1>
            <p className="login-brand-tagline">AI-Powered Research Assistant</p>
          </div>
        </div>

        <div className="login-divider" />

        {/* Description */}
        <p className="login-desc">
          Sign in to access your bookmarks, review history, and personalized research workspace.
        </p>

        {/* Login form */}
        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-input-group">
            <label htmlFor="login-username" className="login-label">ID</label>
            <input
              id="login-username"
              type="text"
              className="login-input"
              placeholder="Enter your ID"
              value={username}
              onChange={(e) => { setUsername(e.target.value); setError(''); }}
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
              onChange={(e) => { setPassword(e.target.value); setError(''); }}
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
      </div>
    </div>
  );
}
