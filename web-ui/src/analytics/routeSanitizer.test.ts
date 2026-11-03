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

  it('allows public blog slug paths and extracts sanitized UTM attribution', () => {
    expect(
      sanitizeRouteForPageView(
        { pathname: '/blog/public-slug?utm_source=google&utm_campaign=Paper Review&utm_medium=social#top' },
        'https://jiphyeonjeon.kr/',
      ),
    ).toEqual({
      page_path: '/blog/public-slug',
      page_location: 'https://jiphyeonjeon.kr/blog/public-slug',
      first_party_payload: {
        utm_source: 'google',
        utm_medium: 'social',
        utm_campaign: 'Paper_Review',
        page_type: 'blog_post',
      },
    });
  });

  it('drops non-blog and email-like UTM values from first-party attribution', () => {
    expect(
      sanitizeRouteForPageView(
        { pathname: '/blog/public-slug', search: '?utm_source=alice@example.com&utm_medium=email' },
        'https://jiphyeonjeon.kr',
      ),
    ).toEqual({
      page_path: '/blog/public-slug',
      page_location: 'https://jiphyeonjeon.kr/blog/public-slug',
      first_party_payload: {
        utm_medium: 'email',
        page_type: 'blog_post',
      },
    });

    expect(
      sanitizeRouteForPageView(
        { pathname: '/', search: '?utm_source=google' },
        'https://jiphyeonjeon.kr',
      ),
    ).toEqual({
      page_path: '/',
      page_location: 'https://jiphyeonjeon.kr/',
    });
  });

  it.each(['/c/abc123', '/c/0f9e8d7c6b5a?x=1', '/C/abc123', '/c/abc123/'])(
    'reports conversation route %s as /c/:id so no conversation id reaches analytics',
    (pathname) => {
      expect(sanitizeRouteForPageView({ pathname }, 'https://jiphyeonjeon.kr')).toEqual({
        page_path: pathname.endsWith('/') ? '/c/:id/' : '/c/:id',
        page_location: `https://jiphyeonjeon.kr${pathname.endsWith('/') ? '/c/:id/' : '/c/:id'}`,
      });
    },
  );

  it('keeps public sample slugs and leaves paths that merely start with c alone', () => {
    expect(sanitizeRouteForPageView({ pathname: '/samples/graphrag-vs-rag' }, 'https://jiphyeonjeon.kr')?.page_path)
      .toBe('/samples/graphrag-vs-rag');
    expect(sanitizeRouteForPageView({ pathname: '/curriculum/abc' }, 'https://jiphyeonjeon.kr')?.page_path)
      .toBe('/curriculum/abc');
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
