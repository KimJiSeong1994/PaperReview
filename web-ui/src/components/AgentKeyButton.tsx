import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Small action-button that copies the current JWT (access_token) from
 * localStorage to the clipboard so the user can paste it into an MCP host
 * (Claude Code / Claude Desktop) as the ``JIPHYEONJEON_TOKEN`` env var.
 *
 * Rendered inline with the MyPage tab buttons but does NOT participate in
 * tab-state — clicking it only copies + flashes a feedback label.
 */

interface AgentKeyButtonProps {
  /** Optional className override — defaults to the MyPage nav-button style. */
  className?: string;
  /** Feedback hold duration in ms. Defaults to 2000. Exposed for tests. */
  feedbackMs?: number;
  /**
   * Token resolver. Defaults to ``localStorage.getItem('access_token')``.
   * Parametrised for testability (unit tests inject a deterministic value
   * without depending on jsdom's Storage implementation).
   */
  getToken?: () => string | null;
}

const defaultGetToken = (): string | null => {
  try {
    return window.localStorage.getItem('access_token');
  } catch {
    return null;
  }
};

function AgentKeyButton({
  className = 'mypage-nav-btn',
  feedbackMs = 2000,
  getToken = defaultGetToken,
}: AgentKeyButtonProps) {
  const [label, setLabel] = useState<string>('Agent Key');
  const timerRef = useRef<number | null>(null);
  // Prevents rapid double-clicks from re-entering the handler while the
  // feedback flash is still showing.
  const busyRef = useRef<boolean>(false);

  const flashLabel = useCallback(
    (next: string) => {
      setLabel(next);
      busyRef.current = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      timerRef.current = window.setTimeout(() => {
        setLabel('Agent Key');
        busyRef.current = false;
        timerRef.current = null;
      }, feedbackMs);
    },
    [feedbackMs],
  );

  const handleClick = useCallback(async () => {
    // Ignore rapid repeat clicks while the previous feedback flash is active.
    if (busyRef.current) {
      return;
    }

    const token = getToken();
    if (!token) {
      // Never log token (missing or not). Only user-facing text.
      alert('로그인이 필요합니다. 먼저 로그인 후 Agent Key 를 복사하세요.');
      return;
    }

    // Modern async clipboard first.
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(token);
        flashLabel('Copied!');
        return;
      } catch {
        // fall through to legacy path below
      }
    }

    // Legacy fallback for browsers without navigator.clipboard.
    // Wrap in try/finally so the temporary textarea (containing the JWT) is
    // always removed from the DOM even if select()/execCommand throws.
    const textarea = document.createElement('textarea');
    let ok = false;
    try {
      textarea.value = token;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.top = '-1000px';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    } finally {
      if (textarea.parentNode) {
        textarea.parentNode.removeChild(textarea);
      }
    }
    flashLabel(ok ? 'Copied!' : 'Copy failed');
  }, [flashLabel, getToken]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, []);

  return (
    <button
      type="button"
      className={className}
      onClick={handleClick}
      title="현재 로그인 토큰을 클립보드로 복사합니다 (Claude MCP agent/skill 연동용)"
      aria-label="Agent Key — 로그인 토큰을 클립보드로 복사"
      data-testid="agent-key-btn"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        width="16"
        height="16"
        aria-hidden="true"
        focusable="false"
        style={{ marginRight: '6px' }}
      >
        <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
      </svg>
      {label}
    </button>
  );
}

export default AgentKeyButton;
