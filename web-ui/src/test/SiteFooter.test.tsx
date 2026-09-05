import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SiteFooter, {
  GITHUB_PROFILE_URL,
  LINKEDIN_PROFILE_URL,
} from '../components/SiteFooter';

function renderFooter(entry = '/') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <SiteFooter />
    </MemoryRouter>,
  );
}

describe('SiteFooter', () => {
  it('renders three labelled columns above the brand line', () => {
    renderFooter();
    for (const heading of ['집현전', '블로그', '만든 사람']) {
      expect(screen.getByRole('navigation', { name: heading })).toBeTruthy();
    }
    expect(screen.getByText('© Jiphyeonjeon (집현전)')).toBeTruthy();
  });

  it('links to search, the blog shelves and the maintainer profiles', () => {
    renderFooter();
    const href = (name: string) => screen.getByRole('link', { name }).getAttribute('href');
    expect(href('논문 검색')).toBe('/');
    expect(href('전체 아티클')).toBe('/blog');
    expect(href('아티클 시리즈')).toBe('/blog#series-index');
    expect(href('태그 전체 보기')).toBe('/blog/tags');
    expect(href('GitHub')).toBe(GITHUB_PROFILE_URL);
    expect(href('LinkedIn')).toBe(LINKEDIN_PROFILE_URL);
  });

  it('routes internal links through the SPA and opens profiles off-site', () => {
    renderFooter();
    // A router <Link> renders a plain in-app href with no target, so clicking
    // it navigates without a full reload; the profile links must not.
    for (const name of ['논문 검색', '전체 아티클', '아티클 시리즈', '태그 전체 보기', '서비스 소개']) {
      const link = screen.getByRole('link', { name });
      expect(link.getAttribute('href')?.startsWith('/')).toBe(true);
      expect(link.getAttribute('target')).toBeNull();
    }
    for (const name of ['GitHub', 'LinkedIn']) {
      const link = screen.getByRole('link', { name });
      expect(link.getAttribute('target')).toBe('_blank');
      expect(link.getAttribute('rel')).toBe('me noopener noreferrer');
    }
  });

  // Every label in this footer is Korean, so every destination is too. The
  // link used to swap in the English /introduce/ on any route that was not
  // /ko/introduce/ — which meant the Korean label 서비스 소개 sent readers to
  // an English page from "/" and from /blog, the two routes it is seen on most.
  it.each(['/ko/introduce/', '/introduce/', '/blog', '/'])(
    'on %s the 서비스 소개 link points at the Korean page',
    (entry) => {
      renderFooter(entry);
      expect(screen.getByRole('link', { name: '서비스 소개' }).getAttribute('href')).toBe(
        '/ko/introduce/',
      );
    },
  );

  it('never links to the English introduce page', () => {
    for (const entry of ['/', '/blog', '/introduce/', '/ko/introduce/']) {
      const { container, unmount } = renderFooter(entry);
      expect(container.querySelector('a[href="/introduce/"]')).toBeNull();
      unmount();
    }
  });
});
