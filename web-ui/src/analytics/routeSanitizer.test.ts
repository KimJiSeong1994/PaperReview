import { describe, expect, it } from 'vitest';
import { sanitizeRouteForPageView } from './routeSanitizer';

describe('sanitizeRouteForPageView', () => {
  it('strips query strings and hashes from public routes', () => {
    expect(
      sanitizeRouteForPageView(
        { pathname: '/', search: '?q=private+paper+title', hash: '#section' },
        'https://jiphyeonjeon.kr',
      ),
    ).toEqual({
      page_path: '/',
      page_location: 'https://jiphyeonjeon.kr/',
    });
  });

  it('allows public blog slug paths without query data', () => {
    expect(
      sanitizeRouteForPageView(
        { pathname: '/blog/public-slug?utm_source=x#top' },
        'https://jiphyeonjeon.kr/',
      ),
    ).toEqual({
      page_path: '/blog/public-slug',
      page_location: 'https://jiphyeonjeon.kr/blog/public-slug',
    });
  });

  it.each(['/mypage', '/mypage/papers', '/admin', '/admin/users', '/share/token-123', '/share/curriculum/token-123'])(
    'suppresses private route %s',
    (pathname) => {
      expect(sanitizeRouteForPageView({ pathname }, 'https://jiphyeonjeon.kr')).toBeNull();
    },
  );

  it.each(['/Admin', '/MYpage/papers', '/%73hare/token-123', '/share%2Ftoken-123', '/%2fshare/curriculum/token-123'])(
    'suppresses encoded or case-varied private route %s',
    (pathname) => {
      expect(sanitizeRouteForPageView({ pathname }, 'https://jiphyeonjeon.kr')).toBeNull();
    },
  );
});
