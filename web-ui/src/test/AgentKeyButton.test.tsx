import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import AgentKeyButton from '../components/AgentKeyButton';

// ── Test helpers ──────────────────────────────────────────────────────
// navigator.clipboard and document.execCommand are not configurable data
// properties in jsdom; every test needs to defineProperty them by hand.
// These helpers capture that setup once so each test reads as a scenario
// rather than a pile of prototype plumbing.

function installClipboard(
  writeText: ((text: string) => Promise<void> | void) | undefined,
): void {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    writable: true,
    value: writeText === undefined ? undefined : { writeText },
  });
}

function installExecCommand(impl: (command: string) => boolean): void {
  (document as unknown as { execCommand: (cmd: string) => boolean }).execCommand = impl;
}

// Click the button and let the async handler's await chain flush.
async function clickBtn(): Promise<void> {
  const btn = screen.getByTestId('agent-key-btn');
  await act(async () => {
    fireEvent.click(btn);
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('AgentKeyButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const store: Record<string, string> = {};
    const shim: Storage = {
      getItem: (k) =>
        Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null,
      setItem: (k, v) => {
        store[k] = String(v);
      },
      removeItem: (k) => {
        delete store[k];
      },
      clear: () => {
        for (const k of Object.keys(store)) delete store[k];
      },
      key: (i) => Object.keys(store)[i] ?? null,
      get length() {
        return Object.keys(store).length;
      },
    };
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      writable: true,
      value: shim,
    });
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      writable: true,
      value: shim,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    installClipboard(undefined);
    (document as unknown as { execCommand?: unknown }).execCommand = undefined;
  });

  it('renders with default label "Agent Key" and a testid', () => {
    render(<AgentKeyButton />);
    const btn = screen.getByTestId('agent-key-btn');
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent('Agent Key');
    expect(btn.getAttribute('type')).toBe('button');
  });

  it('uses the mypage-nav-btn class so it matches existing tab styling', () => {
    render(<AgentKeyButton />);
    const btn = screen.getByTestId('agent-key-btn');
    expect(btn.className).toContain('mypage-nav-btn');
    expect(btn.className).not.toContain('mypage-nav-btn-active');
  });

  it('alerts and skips clipboard when no token is stored', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const writeText = vi.fn();
    installClipboard(writeText);

    render(<AgentKeyButton getToken={() => null} />);
    await clickBtn();

    expect(alertSpy).toHaveBeenCalledOnce();
    expect(alertSpy.mock.calls[0][0]).toMatch(/로그인/);
    expect(writeText).not.toHaveBeenCalled();
  });

  it('copies token via navigator.clipboard.writeText and flashes Copied!', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    installClipboard(writeText);

    render(<AgentKeyButton feedbackMs={1000} getToken={() => 'jwt-abc-123'} />);
    await clickBtn();

    expect(writeText).toHaveBeenCalledWith('jwt-abc-123');
    await waitFor(() => {
      expect(screen.getByTestId('agent-key-btn')).toHaveTextContent('Copied!');
    });
  });

  it('resets the label back to "Agent Key" after the feedback window', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const writeText = vi.fn().mockResolvedValue(undefined);
    installClipboard(writeText);

    render(<AgentKeyButton feedbackMs={1000} getToken={() => 'jwt-xyz'} />);
    await clickBtn();

    await waitFor(() => {
      expect(screen.getByTestId('agent-key-btn')).toHaveTextContent('Copied!');
    });

    act(() => {
      vi.advanceTimersByTime(1100);
    });

    await waitFor(() => {
      expect(screen.getByTestId('agent-key-btn')).toHaveTextContent('Agent Key');
    });
  });

  it('falls back to execCommand when navigator.clipboard.writeText rejects', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    installClipboard(writeText);
    const execCmd = vi.fn(() => true);
    installExecCommand(execCmd);

    render(<AgentKeyButton feedbackMs={500} getToken={() => 'jwt-legacy'} />);
    await clickBtn();

    await waitFor(() => {
      expect(execCmd).toHaveBeenCalledWith('copy');
    });
    expect(screen.getByTestId('agent-key-btn')).toHaveTextContent('Copied!');
  });

  it('shows "Copy failed" when both modern and legacy paths fail', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    installClipboard(writeText);
    const execCmd = vi.fn(() => false);
    installExecCommand(execCmd);

    render(<AgentKeyButton feedbackMs={500} getToken={() => 'jwt-broken'} />);
    await clickBtn();

    await waitFor(() => {
      expect(screen.getByTestId('agent-key-btn')).toHaveTextContent('Copy failed');
    });
    expect(execCmd).toHaveBeenCalledWith('copy');
  });

  it('has aria-label + aria-hidden SVG for accessibility', () => {
    render(<AgentKeyButton />);
    const btn = screen.getByTestId('agent-key-btn');
    expect(btn.getAttribute('aria-label')).toMatch(/Agent Key/);
    const svg = btn.querySelector('svg');
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
  });

  it('ignores rapid double-click while feedback is showing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const writeText = vi.fn().mockResolvedValue(undefined);
    installClipboard(writeText);

    render(<AgentKeyButton feedbackMs={1000} getToken={() => 'jwt-guard'} />);
    await clickBtn();
    await clickBtn(); // second click during flash — should be a no-op
    expect(writeText).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(1100);
    });
    await clickBtn();
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledTimes(2);
    });
  });

  it('removes the temporary textarea even when select throws', async () => {
    installClipboard(undefined); // force legacy branch
    installExecCommand(() => {
      throw new Error('unsupported');
    });

    render(<AgentKeyButton feedbackMs={300} getToken={() => 'jwt-finally'} />);
    const before = document.querySelectorAll('textarea').length;
    await clickBtn();
    const after = document.querySelectorAll('textarea').length;
    expect(after).toBe(before);
    expect(screen.getByTestId('agent-key-btn')).toHaveTextContent('Copy failed');
  });

  it('never writes the token to console.log', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    installClipboard(writeText);
    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    render(<AgentKeyButton getToken={() => 'jwt-sensitive-SHOULD-NOT-LOG'} />);
    await clickBtn();

    expect(writeText).toHaveBeenCalled();
    for (const call of consoleSpy.mock.calls) {
      const joined = call.map((x) => String(x)).join(' ');
      expect(joined).not.toContain('jwt-sensitive-SHOULD-NOT-LOG');
    }
    consoleSpy.mockRestore();
  });
});
