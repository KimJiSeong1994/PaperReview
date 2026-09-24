import { Suspense, lazy } from 'react';
import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { getLoadedBlogPage, preloadBlogPage } from '../utils/blogPageLoader';

vi.mock('../components/BlogPage', () => ({ default: () => <p>Ready article</p> }));

it('makes a preloaded article synchronously available without a suspense fallback', async () => {
  const module = await preloadBlogPage();
  expect(getLoadedBlogPage()).toBe(module.default);
  const Fallback = vi.fn(() => <p>Loading article</p>);
  const Component = getLoadedBlogPage() ?? lazy(preloadBlogPage);
  render(<Suspense fallback={<Fallback />}><Component isAdmin={false} /></Suspense>);
  expect(Fallback).not.toHaveBeenCalled();
  expect(screen.getByText('Ready article')).toBeInTheDocument();
  expect(screen.queryByText('Loading article')).not.toBeInTheDocument();
});
