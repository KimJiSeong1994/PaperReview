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

  it('renders sign-in form by default', () => {
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    expect(screen.getByPlaceholderText('Enter your ID')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Enter your password')).toBeInTheDocument();
  });

  it('switches to sign-up mode', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    await user.click(screen.getByText('Sign Up'));
    expect(screen.getByPlaceholderText('Re-enter your password')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Letters, numbers, underscore')).toBeInTheDocument();
  });

  it('shows error when sign-in fields are empty', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    // "Sign In" appears as both tab button and submit button; pick the submit
    const allSignInBtns = screen.getAllByRole('button', { name: /sign in/i });
    const submitBtn = allSignInBtns.find(btn => btn.getAttribute('type') === 'submit')!;
    await user.click(submitBtn);
    expect(screen.getByText('Please enter your ID and password.')).toBeInTheDocument();
  });

  it('closes on close button click', async () => {
    const user = userEvent.setup();
    render(<LoginModal onLoginSuccess={onLoginSuccess} onClose={onClose} />);
    const closeBtn = screen.getByLabelText('Close');
    await user.click(closeBtn);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
