import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useBlock } from '../components/adminShared';
import type { AdminWindowDays } from '../api/client';

describe('admin period identity', () => {
  it('hides the previous period immediately and ignores late responses', async () => {
    const requests = new Map<number, (response: { data: number }) => void>();
    const fetcher = vi.fn((days: AdminWindowDays) => new Promise<{ data: number }>((resolve) => requests.set(days, resolve)));
    const { result, rerender } = renderHook(({ days }: { days: AdminWindowDays }) => useBlock(fetcher, days), { initialProps: { days: 7 } });
    await waitFor(() => expect(requests.has(7)).toBe(true));
    await act(async () => requests.get(7)!({ data: 7 }));
    expect(result.current.data).toBe(7);
    rerender({ days: 28 });
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(requests.has(28)).toBe(true));
    rerender({ days: 90 });
    await waitFor(() => expect(requests.has(90)).toBe(true));
    await act(async () => requests.get(90)!({ data: 90 }));
    await act(async () => requests.get(28)!({ data: 28 }));
    expect(result.current.data).toBe(90);
  });

  it('shows failure instead of old data and supports retry', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ data: 7 }).mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ data: 28 });
    const { result, rerender } = renderHook(({ days }: { days: AdminWindowDays }) => useBlock(fetcher, days), { initialProps: { days: 7 } });
    await waitFor(() => expect(result.current.data).toBe(7));
    rerender({ days: 28 });
    await waitFor(() => expect(result.current.error).toBe('unavailable'));
    expect(result.current.data).toBeNull();
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.data).toBe(28));
    expect(result.current.error).toBeNull();
  });
});
