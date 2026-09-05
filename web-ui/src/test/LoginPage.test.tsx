import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoginModal from '../components/LoginPage';

describe('LoginModal', () => {
  const onLoginSuccess = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('is a labelled modal dialog', () => {
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('Jiphyeonjeon');
    // The card used to carry its own <h1>, which meant opening it put a second
    // h1 on a page that already has one. Its visible title now names the dialog.
    expect(dialog.querySelector('h1')).toBeNull();
    expect(dialog.querySelector('h2')?.id).toBe('login-dialog-title');
  });

  it('opens with the caret in the first field', () => {
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    expect(document.activeElement).toBe(screen.getByPlaceholderText('아이디를 입력하세요'));
  });

  // Without a trap, Tab walked straight out of the card into the page behind it.
  it('keeps Tab inside the dialog', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    const dialog = screen.getByRole('dialog');
    const items = dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const first = items[0];
    const last = items[items.length - 1];

    last.focus();
    await user.tab();
    expect(document.activeElement).toBe(first);

    first.focus();
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(last);
  });

  // Closing used to drop focus on <body>, leaving a keyboard user at the top of
  // the document with no idea where they had been.
  it('hands focus back to whatever opened it', () => {
    const opener = document.createElement('button');
    opener.textContent = '마이페이지';
    document.body.appendChild(opener);
    opener.focus();
    expect(document.activeElement).toBe(opener);

    const view = render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    expect(document.activeElement).not.toBe(opener);

    view.unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it('renders sign-in form by default', () => {
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    expect(screen.getByPlaceholderText('아이디를 입력하세요')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('비밀번호를 입력하세요')).toBeInTheDocument();
  });

  it('switches to sign-up mode', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await user.click(screen.getByText('회원가입'));
    expect(screen.getByPlaceholderText('비밀번호를 다시 입력하세요')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('영문, 숫자, 밑줄')).toBeInTheDocument();
  });

  it('shows error when sign-in fields are empty', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    // "Sign In" appears as both tab button and submit button; pick the submit
    const allSignInBtns = screen.getAllByRole('button', { name: '로그인' });
    const submitBtn = allSignInBtns.find(btn => btn.getAttribute('type') === 'submit')!;
    await user.click(submitBtn);
    expect(screen.getByText('아이디와 비밀번호를 입력해주세요.')).toBeInTheDocument();
  });

  it('closes on close button click', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    const closeBtn = screen.getByLabelText('닫기');
    await user.click(closeBtn);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
