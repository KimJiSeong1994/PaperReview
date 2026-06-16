import { StrictMode } from 'react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AnalyticsRouteTracker from '../components/AnalyticsRouteTracker';
import { ANALYTICS_CONSENT_CHANGED_EVENT, trackPageView } from '../analytics/ga4';

vi.mock('../analytics/ga4', () => ({
  ANALYTICS_CONSENT_CHANGED_EVENT: 'analytics-consent-changed',
  trackPageView: vi.fn(),
}));

function TestRoutes() {
  return (
    <>
      <AnalyticsRouteTracker origin="https://jiphyeonjeon.kr" />
      <nav>
        <Link to="/blog/public-slug?utm_source=x#top">Blog post</Link>
        <Link to="/share/private-token?q=secret">Private share</Link>
        <Link to="/?q=raw+paper+title">Home search</Link>
      </nav>
      <Routes>
        <Route path="*" element={<h1>Route</h1>} />
      </Routes>
    </>
  );
}

describe('AnalyticsRouteTracker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(trackPageView).mockReturnValue(true);
  });

  it('tracks sanitized initial public page views once under StrictMode', () => {
    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/?q=raw+paper+title']}>
          <TestRoutes />
        </MemoryRouter>
      </StrictMode>,
    );

    expect(trackPageView).toHaveBeenCalledTimes(1);
    expect(trackPageView).toHaveBeenCalledWith({
      page_path: '/',
      page_location: 'https://jiphyeonjeon.kr/',
    });
    expect(JSON.stringify(vi.mocked(trackPageView).mock.calls)).not.toContain('raw+paper+title');
    expect(JSON.stringify(vi.mocked(trackPageView).mock.calls)).not.toContain('?q=');
  });

  it('tracks public route changes without query/hash and suppresses private token routes', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/']}>
        <TestRoutes />
      </MemoryRouter>,
    );

    expect(trackPageView).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('link', { name: 'Blog post' }));
    expect(trackPageView).toHaveBeenLastCalledWith({
      page_path: '/blog/public-slug',
      page_location: 'https://jiphyeonjeon.kr/blog/public-slug',
      first_party_payload: {
        utm_source: 'x',
        page_type: 'blog_post',
      },
    });

    await user.click(screen.getByRole('link', { name: 'Private share' }));
    expect(trackPageView).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(vi.mocked(trackPageView).mock.calls)).not.toContain('private-token');

    await user.click(screen.getByRole('link', { name: 'Home search' }));
    expect(trackPageView).toHaveBeenCalledTimes(3);
    expect(trackPageView).toHaveBeenLastCalledWith({
      page_path: '/',
      page_location: 'https://jiphyeonjeon.kr/',
    });
    expect(JSON.stringify(vi.mocked(trackPageView).mock.calls)).not.toContain('raw+paper+title');
  });

  it('retries the current route after analytics consent changes when the first dispatch was suppressed', () => {
    vi.mocked(trackPageView).mockReturnValueOnce(false).mockReturnValue(true);

    render(
      <MemoryRouter initialEntries={['/blog/public-slug']}>
        <TestRoutes />
      </MemoryRouter>,
    );

    expect(trackPageView).toHaveBeenCalledTimes(1);

    act(() => {
      window.dispatchEvent(new CustomEvent(ANALYTICS_CONSENT_CHANGED_EVENT, { detail: { consent: 'granted' } }));
    });

    expect(trackPageView).toHaveBeenCalledTimes(2);
    expect(trackPageView).toHaveBeenLastCalledWith({
      page_path: '/blog/public-slug',
      page_location: 'https://jiphyeonjeon.kr/blog/public-slug',
    });
  });
});
