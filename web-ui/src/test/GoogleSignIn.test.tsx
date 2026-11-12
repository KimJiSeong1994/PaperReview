import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import GoogleSignIn from '../components/GoogleSignIn';
import { createGoogleChallenge, loginWithGoogle, type AuthSession } from '../api/auth';
import { api } from '../api/base';
import { trackLoginEvent, trackSignUpEvent } from '../analytics/events';

vi.mock('../api/auth', async () => ({
  ...await vi.importActual('../api/auth'), createGoogleChallenge: vi.fn(), loginWithGoogle: vi.fn(),
}));
vi.mock('../analytics/events', () => ({ trackLoginEvent: vi.fn(), trackSignUpEvent: vi.fn() }));

type GoogleSdk = NonNullable<Window['google']>['accounts']['id'];
const initialize = vi.fn<GoogleSdk['initialize']>();
const renderButton = vi.fn<GoogleSdk['renderButton']>((container) => {
  const button = document.createElement('button');
  button.textContent = 'Google 계정으로 계속하기';
  container.appendChild(button);
});
const sdk = { initialize, renderButton };
const SESSION: AuthSession = { access_token: 'app-jwt', token_type: 'bearer', username: 'existing_user', role: 'admin', is_new_user: false };
const onLoginSuccess = vi.fn();
let values: Record<string, string>;
const credentialCallback = () => initialize.mock.lastCall![0].callback;
const httpError = (status: number, detail?: string) => ({ isAxiosError: true, response: { status, data: { detail } } });

beforeEach(() => {
  vi.clearAllMocks();
  window.google = { accounts: { id: sdk } };
  values = {};
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values[key] ?? null,
    setItem: (key: string, value: string) => { values[key] = value; },
    removeItem: (key: string) => { delete values[key]; },
  });
  vi.mocked(createGoogleChallenge).mockReset().mockResolvedValue({ client_id: 'configured-client', nonce: 'fresh-nonce' });
  vi.mocked(loginWithGoogle).mockReset().mockResolvedValue(SESSION);
});
afterEach(() => {
  delete window.google;
  document.getElementById('google-identity-client')?.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const renderGoogle = () => render(<GoogleSignIn onLoginSuccess={onLoginSuccess} />);
async function startLinking() {
  const user = userEvent.setup();
  renderGoogle();
  await screen.findByText('Google 계정으로 계속하기');
  await user.click(screen.getByRole('button', { name: '기존 계정 연결' }));
  return user;
}

describe('GoogleSignIn', () => {
  it('uses the Google-rendered button with the server challenge and no One Tap', async () => {
    renderGoogle();
    await screen.findByText('Google 계정으로 계속하기');
    expect(createGoogleChallenge).toHaveBeenCalledWith(undefined, expect.any(AbortSignal));
    expect(initialize).toHaveBeenCalledWith(expect.objectContaining({ client_id: 'configured-client', nonce: 'fresh-nonce', auto_select: false }));
    expect(renderButton).toHaveBeenCalledWith(expect.any(HTMLElement), expect.objectContaining({ type: 'standard', locale: 'ko', text: 'continue_with' }));
    expect(screen.queryByLabelText('기존 비밀번호')).not.toBeInTheDocument();
    expect(screen.getByText(/기존 아이디가 있다면 먼저/)).toBeInTheDocument();
  });

  it('starts only one cookie challenge under StrictMode effect replay', async () => {
    render(<StrictMode><GoogleSignIn onLoginSuccess={onLoginSuccess} /></StrictMode>);
    await screen.findByText('Google 계정으로 계속하기');
    expect(createGoogleChallenge).toHaveBeenCalledOnce();
    expect(initialize).toHaveBeenCalledOnce();
  });

  it('stores only the application session and tracks the verified Google login', async () => {
    renderGoogle();
    await screen.findByText('Google 계정으로 계속하기');
    await act(async () => credentialCallback()({ credential: 'google-id-token' }));
    expect(loginWithGoogle).toHaveBeenCalledWith('google-id-token', expect.any(AbortSignal));
    expect(values).toEqual({ access_token: 'app-jwt', username: 'existing_user', user_role: 'admin' });
    expect(JSON.stringify(values)).not.toContain('google-id-token');
    expect(onLoginSuccess).toHaveBeenCalledOnce();
    expect(trackLoginEvent).toHaveBeenCalledWith();
    expect(trackSignUpEvent).not.toHaveBeenCalled();
  });

  it('tracks signup only when the backend confirms a newly created account', async () => {
    vi.mocked(loginWithGoogle).mockResolvedValue({ ...SESSION, is_new_user: true });
    renderGoogle();
    await screen.findByText('Google 계정으로 계속하기');
    await act(async () => credentialCallback()({ credential: 'google-id-token' }));
    expect(trackSignUpEvent).toHaveBeenCalledWith();
  });

  it('verifies the old account before rendering a Google linking button', async () => {
    const user = await startLinking();
    expect(screen.queryByText('Google 계정으로 계속하기')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('기존 아이디'), 'old_account');
    await user.type(screen.getByLabelText('기존 비밀번호'), 'old-password');
    await user.click(screen.getByRole('button', { name: '기존 계정 확인' }));
    expect(await screen.findByText('Google 계정으로 계속하기')).toBeInTheDocument();
    expect(createGoogleChallenge).toHaveBeenLastCalledWith({ username: 'old_account', password: 'old-password' }, expect.any(AbortSignal));
    expect(screen.queryByLabelText('기존 비밀번호')).not.toBeInTheDocument();
    await act(async () => credentialCallback()({ credential: 'google-link-token' }));
    expect(loginWithGoogle).toHaveBeenCalledWith('google-link-token', expect.any(AbortSignal));
    expect(values.username).toBe('existing_user');
    expect(values.user_role).toBe('admin');
  });

  it('does not render a linking button after rejected credentials', async () => {
    const user = await startLinking();
    vi.mocked(createGoogleChallenge).mockRejectedValueOnce(httpError(401));
    await user.type(screen.getByLabelText('기존 아이디'), 'old_account');
    await user.type(screen.getByLabelText('기존 비밀번호'), 'wrong');
    await user.click(screen.getByRole('button', { name: '기존 계정 확인' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('아이디 또는 비밀번호가 올바르지 않습니다');
    expect(screen.queryByText('Google 계정으로 계속하기')).not.toBeInTheDocument();
    expect(loginWithGoogle).not.toHaveBeenCalled();
  });

  it('does not submit duplicate account proofs in the same event turn', async () => {
    const user = await startLinking();
    await user.type(screen.getByLabelText('기존 아이디'), 'old_account');
    await user.type(screen.getByLabelText('기존 비밀번호'), 'old-password');
    vi.mocked(createGoogleChallenge).mockReturnValueOnce(new Promise(() => {}));
    const calls = vi.mocked(createGoogleChallenge).mock.calls.length;
    const form = screen.getByRole('button', { name: '기존 계정 확인' }).closest('form')!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(createGoogleChallenge).toHaveBeenCalledTimes(calls + 1);
  });

  it('rejects duplicate callbacks and ignores completion after unmount', async () => {
    let resolve!: (value: AuthSession) => void;
    vi.mocked(loginWithGoogle).mockReturnValue(new Promise((done) => { resolve = done; }));
    const view = renderGoogle();
    await screen.findByText('Google 계정으로 계속하기');
    const callback = credentialCallback();
    act(() => {
      callback({ credential: 'same-token' });
      callback({ credential: 'same-token' });
    });
    expect(loginWithGoogle).toHaveBeenCalledOnce();
    view.unmount();
    await act(async () => resolve(SESSION));
    callback({ credential: 'late-token' });
    expect(onLoginSuccess).not.toHaveBeenCalled();
    expect(values).toEqual({});
    expect(loginWithGoogle).toHaveBeenCalledOnce();
  });

  it('requests a fresh nonce after verification failure and ignores the old callback', async () => {
    vi.mocked(loginWithGoogle).mockRejectedValueOnce(httpError(401));
    vi.mocked(createGoogleChallenge)
      .mockResolvedValueOnce({ client_id: 'configured-client', nonce: 'nonce-one' })
      .mockResolvedValueOnce({ client_id: 'configured-client', nonce: 'nonce-two' });
    renderGoogle();
    await screen.findByText('Google 계정으로 계속하기');
    const oldCallback = credentialCallback();
    await act(async () => oldCallback({ credential: 'expired' }));
    await waitFor(() => expect(initialize).toHaveBeenLastCalledWith(expect.objectContaining({ nonce: 'nonce-two' })));
    expect(screen.getByRole('alert')).toHaveTextContent('Google 인증이 만료');
    oldCallback({ credential: 'expired' });
    expect(loginWithGoogle).toHaveBeenCalledOnce();
    await act(async () => credentialCallback()({ credential: 'new-token' }));
    expect(onLoginSuccess).toHaveBeenCalledOnce();
  });

  it('returns linking failures to password proof instead of reusing a consumed nonce', async () => {
    const user = await startLinking();
    await user.type(screen.getByLabelText('기존 아이디'), 'old_account');
    await user.type(screen.getByLabelText('기존 비밀번호'), 'old-password');
    await user.click(screen.getByRole('button', { name: '기존 계정 확인' }));
    await screen.findByText('Google 계정으로 계속하기');
    vi.mocked(loginWithGoogle).mockRejectedValueOnce(httpError(409, 'google_identity_conflict'));
    await act(async () => credentialCallback()({ credential: 'conflict' }));
    expect(await screen.findByLabelText('기존 비밀번호')).toHaveValue('');
    expect(screen.getByRole('alert')).toHaveTextContent('다른 집현전 계정');
    expect(screen.queryByText('Google 계정으로 계속하기')).not.toBeInTheDocument();
    expect(onLoginSuccess).not.toHaveBeenCalled();
  });

  it('shows Google SDK load failures and loads a new script on retry', async () => {
    delete window.google;
    const user = userEvent.setup();
    renderGoogle();
    await waitFor(() => expect(document.getElementById('google-identity-client')).toBeInTheDocument());
    const script = document.getElementById('google-identity-client')!;
    expect(script).toHaveAttribute('src', 'https://accounts.google.com/gsi/client');
    fireEvent.error(script);
    expect(await screen.findByRole('alert')).toHaveTextContent('Google 로그인 버튼을 불러오지 못했습니다');
    expect(script).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(document.getElementById('google-identity-client')).toBeInTheDocument());
    const retryScript = document.getElementById('google-identity-client')!;
    expect(retryScript).not.toBe(script);
    window.google = { accounts: { id: sdk } };
    fireEvent.load(retryScript);
    expect(await screen.findByText('Google 계정으로 계속하기')).toBeInTheDocument();
    expect(createGoogleChallenge).toHaveBeenCalledTimes(2);
  });

  it('makes challenge failures retryable without rendering Google credentials UI', async () => {
    vi.mocked(createGoogleChallenge).mockRejectedValueOnce(httpError(429));
    const user = userEvent.setup();
    renderGoogle();
    expect(await screen.findByRole('alert')).toHaveTextContent('요청이 너무 많습니다');
    expect(renderButton).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('Google 계정으로 계속하기')).toBeInTheDocument();
  });
});

describe('Google auth transport', () => {
  it('includes challenge cookies on both POSTs without sending local identity to the final exchange', async () => {
    const actual = await vi.importActual<typeof import('../api/auth')>('../api/auth');
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const controller = new AbortController();
    await actual.createGoogleChallenge({ username: 'old_user', password: 'proof' }, controller.signal);
    expect(post).toHaveBeenLastCalledWith('/api/auth/google/challenge', { username: 'old_user', password: 'proof' }, { baseURL: '', withCredentials: true, signal: controller.signal });
    await actual.loginWithGoogle('signed-token', controller.signal);
    expect(post).toHaveBeenLastCalledWith('/api/auth/google', { credential: 'signed-token' }, { baseURL: '', withCredentials: true, signal: controller.signal });
  });
});
