import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoginModal from '../components/LoginPage';
import { getAuthConfig } from '../api/client';

vi.mock('../api/client', async () => ({
  ...await vi.importActual('../api/client'),
  getAuthConfig: vi.fn(),
}));
vi.mock('../components/GoogleSignIn', () => ({ default: () => <div>Google 로그인 테스트</div> }));
const PASSWORD_CONFIG = { google_enabled: false, google_client_id: null, password_login_enabled: true, registration_enabled: true };


describe('LoginModal', () => {
  const onLoginSuccess = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getAuthConfig).mockResolvedValue(PASSWORD_CONFIG);
  });

  it('is a labelled modal dialog', async () => {
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await screen.findByPlaceholderText('아이디를 입력하세요');
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('Jiphyeonjeon');
    // The card used to carry its own <h1>, which meant opening it put a second
    // h1 on a page that already has one. Its visible title now names the dialog.
    expect(dialog.querySelector('h1')).toBeNull();
    expect(dialog.querySelector('h2')?.id).toBe('login-dialog-title');
  });

  it('opens with the caret in the first field', async () => {
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    const field = await screen.findByPlaceholderText('아이디를 입력하세요');
    expect(document.activeElement).toBe(field);
  });

  // Without a trap, Tab walked straight out of the card into the page behind it.
  it('keeps Tab inside the dialog', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await screen.findByPlaceholderText('아이디를 입력하세요');
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
  it('hands focus back to whatever opened it', async () => {
    const opener = document.createElement('button');
    opener.textContent = '마이페이지';
    document.body.appendChild(opener);
    opener.focus();
    expect(document.activeElement).toBe(opener);

    const view = render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await screen.findByPlaceholderText('아이디를 입력하세요');
    expect(document.activeElement).not.toBe(opener);

    view.unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it('renders sign-in form by default', async () => {
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    expect(await screen.findByPlaceholderText('아이디를 입력하세요')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('비밀번호를 입력하세요')).toBeInTheDocument();
  });

  it('switches to sign-up mode', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await user.click(await screen.findByText('회원가입'));
    expect(screen.getByPlaceholderText('비밀번호를 다시 입력하세요')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('영문, 숫자, 밑줄')).toBeInTheDocument();
  });

  it('shows error when sign-in fields are empty', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    // "Sign In" appears as both tab button and submit button; pick the submit
    await screen.findByPlaceholderText('아이디를 입력하세요');
    const allSignInBtns = screen.getAllByRole('button', { name: '로그인' });
    const submitBtn = allSignInBtns.find(btn => btn.getAttribute('type') === 'submit')!;
    await user.click(submitBtn);
    expect(screen.getByText('아이디와 비밀번호를 입력해주세요.')).toBeInTheDocument();
  });

  it('closes on close button click', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await screen.findByPlaceholderText('아이디를 입력하세요');
    const closeBtn = screen.getByLabelText('닫기');
    await user.click(closeBtn);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('uses Google login and removes password signup when the provider is enabled', async () => {
    vi.mocked(getAuthConfig).mockResolvedValue({ google_enabled: true, google_client_id: 'web-client', password_login_enabled: false, registration_enabled: false });
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    expect(await screen.findByText('Google 로그인 테스트')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('아이디를 입력하세요')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '회원가입' })).not.toBeInTheDocument();
  });

  it('shows retry on config failure instead of silently enabling passwords', async () => {
    vi.mocked(getAuthConfig).mockRejectedValueOnce(new Error('unavailable'));
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('로그인 설정을 불러오지 못했습니다');
    expect(screen.queryByPlaceholderText('아이디를 입력하세요')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByPlaceholderText('아이디를 입력하세요')).toBeInTheDocument();
  });

  it('does not offer registration when the server disables it', async () => {
    vi.mocked(getAuthConfig).mockResolvedValue({ ...PASSWORD_CONFIG, registration_enabled: false });
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await screen.findByPlaceholderText('아이디를 입력하세요');
    expect(screen.queryByRole('button', { name: '회원가입' })).not.toBeInTheDocument();
  });

});
