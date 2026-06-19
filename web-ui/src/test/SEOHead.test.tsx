import { afterEach, describe, expect, it } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import SEOHead from '../components/SEOHead';

function meta(selector: string): HTMLMetaElement | null {
  return document.head.querySelector(selector);
}

describe('SEOHead', () => {
  afterEach(() => {
    document.head.innerHTML = '';
    document.title = '';
  });

  it('sets title, description, canonical, Open Graph, and Twitter metadata', async () => {
    render(
      <SEOHead
        title="Paper Review Blog"
        description="Research writeups and product notes."
        canonical="https://jiphyeonjeon.kr/blog"
      />,
    );

    await waitFor(() => {
      expect(document.title).toBe('Paper Review Blog');
    });

    expect(meta('meta[name="description"]')).toHaveAttribute(
      'content',
      'Research writeups and product notes.',
    );
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'https://jiphyeonjeon.kr/blog',
    );
    expect(meta('meta[property="og:title"]')).toHaveAttribute('content', 'Paper Review Blog');
    expect(meta('meta[property="og:description"]')).toHaveAttribute(
      'content',
      'Research writeups and product notes.',
    );
    expect(meta('meta[property="og:url"]')).toHaveAttribute(
      'content',
      'https://jiphyeonjeon.kr/blog',
    );
    expect(meta('meta[name="twitter:card"]')).toHaveAttribute('content', 'summary_large_image');
    expect(meta('meta[name="twitter:title"]')).toHaveAttribute('content', 'Paper Review Blog');
  });

  it('updates managed tags without creating duplicates', async () => {
    const { rerender } = render(
      <SEOHead
        title="First title"
        description="First description"
        canonical="https://jiphyeonjeon.kr/blog/first"
      />,
    );

    await waitFor(() => expect(document.title).toBe('First title'));

    rerender(
      <SEOHead
        title="Second title"
        description="Second description"
        canonical="https://jiphyeonjeon.kr/blog/second"
      />,
    );

    await waitFor(() => expect(document.title).toBe('Second title'));

    expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(document.head.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
    expect(document.head.querySelectorAll('meta[property="og:title"]')).toHaveLength(1);
    expect(meta('meta[name="description"]')).toHaveAttribute('content', 'Second description');
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'https://jiphyeonjeon.kr/blog/second',
    );
  });

  it('defaults og:image/twitter:image to og-default.jpg and sets og dimensions + locale', async () => {
    render(
      <SEOHead
        title="Paper Review Blog"
        description="Research writeups and product notes."
        canonical="https://jiphyeonjeon.kr/blog"
      />,
    );

    await waitFor(() => {
      expect(document.title).toBe('Paper Review Blog');
    });

    expect(meta('meta[property="og:image"]')).toHaveAttribute(
      'content',
      'https://jiphyeonjeon.kr/og-default.jpg',
    );
    expect(meta('meta[name="twitter:image"]')).toHaveAttribute(
      'content',
      'https://jiphyeonjeon.kr/og-default.jpg',
    );
    expect(meta('meta[property="og:image:width"]')).toHaveAttribute('content', '1200');
    expect(meta('meta[property="og:image:height"]')).toHaveAttribute('content', '630');
    expect(meta('meta[property="og:locale"]')).toHaveAttribute('content', 'en_US');
    expect(meta('meta[property="og:site_name"]')).toHaveAttribute('content', 'Jiphyeonjeon');
  });

  it('renders og:locale from the locale prop and sets the alternate to the opposite', async () => {
    render(
      <SEOHead
        title="논문 리뷰"
        description="한국어 블로그 글입니다."
        canonical="https://jiphyeonjeon.kr/blog/korean-post"
        locale="ko_KR"
      />,
    );

    await waitFor(() => {
      expect(document.title).toBe('논문 리뷰');
    });

    expect(meta('meta[property="og:locale"]')).toHaveAttribute('content', 'ko_KR');
    expect(meta('meta[property="og:locale:alternate"]')).toHaveAttribute('content', 'en_US');
  });

  it('sets robots noindex,nofollow for private tokenized pages', async () => {
    render(
      <SEOHead
        title="Shared report"
        description="Private shared report"
        robots="noindex,nofollow"
      />,
    );

    await waitFor(() => {
      expect(meta('meta[name="robots"]')).toHaveAttribute('content', 'noindex,nofollow');
    });
  });
});
