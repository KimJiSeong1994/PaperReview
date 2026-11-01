import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SoulPanel from '../components/mypage/SoulPanel';
import { clearSoul, deleteSoulMemory, fetchSoul, saveSoulProfile } from '../api/soul';
import type { Soul } from '../types';

vi.mock('../api/soul', () => ({
  SOUL_PROFILE_MAX: 2000,
  fetchSoul: vi.fn(),
  saveSoulProfile: vi.fn(),
  deleteSoulMemory: vi.fn(),
  clearSoul: vi.fn(),
}));

const soul = (): Soul => ({
  user_md: '그래프 검색을 연구해요.',
  markdown: '',
  memories: [
    { id: 'm1', kind: 'preference', text: '요약은 짧게', created_at: '' },
    { id: 'm2', kind: 'topic', text: 'GraphRAG', created_at: '' },
    { id: 'm3', kind: 'topic', text: '장기 대화 기억', created_at: '' },
    { id: 'm4', kind: 'paper', text: 'HippoRAG', created_at: '' },
  ],
});

async function renderPanel() {
  render(<SoulPanel />);
  await screen.findByRole('heading', { name: /기억한 내용/ });
}

describe('SoulPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchSoul).mockReset().mockResolvedValue(soul());
    vi.mocked(saveSoulProfile).mockReset();
    vi.mocked(deleteSoulMemory).mockReset().mockResolvedValue({ ok: true });
    vi.mocked(clearSoul).mockReset().mockResolvedValue({ deleted: 4 });
  });

  it('groups memories by kind with Korean labels and prefills the profile', async () => {
    await renderPanel();
    expect(screen.getByRole('heading', { name: '집현전이 기억하는 것' })).toBeTruthy();
    const topics = screen.getByRole('region', { name: '관심 주제' });
    expect(within(topics).getAllByRole('listitem')).toHaveLength(2);
    expect(within(screen.getByRole('region', { name: '선호' })).getByText('요약은 짧게')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: '논문' })).getByText('HippoRAG')).toBeTruthy();
    expect(screen.queryByRole('region', { name: '사실' })).toBeNull();
    expect((screen.getByLabelText('나에 대해 알려주기') as HTMLTextAreaElement).value).toBe('그래프 검색을 연구해요.');
    expect(screen.getByText('13/2000자')).toBeTruthy();
  });

  it('deletes one memory through the API and drops it from the list', async () => {
    await renderPanel();
    const topics = screen.getByRole('region', { name: '관심 주제' });
    await act(async () => {
      fireEvent.click(within(topics).getAllByRole('button', { name: '기억 삭제' })[0]);
    });
    expect(deleteSoulMemory).toHaveBeenCalledWith('m2');
    expect(screen.queryByText('GraphRAG')).toBeNull();
    expect(screen.getByText('장기 대화 기억')).toBeTruthy();
  });

  it('saves the edited profile with PUT', async () => {
    vi.mocked(saveSoulProfile).mockResolvedValue({ user_md: '수식은 꼭 보여 주세요.' });
    await renderPanel();
    const save = screen.getByRole('button', { name: '저장' });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('나에 대해 알려주기'), { target: { value: '수식은 꼭 보여 주세요.' } });
    await act(async () => { fireEvent.click(save); });
    expect(saveSoulProfile).toHaveBeenCalledWith('수식은 꼭 보여 주세요.');
    expect(screen.getByText('저장했어요.')).toBeTruthy();
  });

  it('clears everything only after the second, confirming click', async () => {
    await renderPanel();
    fireEvent.click(screen.getByRole('button', { name: '모두 지우기' }));
    expect(clearSoul).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '취소' }));
    expect(screen.getByRole('button', { name: '모두 지우기' })).toBeTruthy();

    vi.mocked(fetchSoul).mockResolvedValueOnce({ user_md: '', markdown: '', memories: [] });
    fireEvent.click(screen.getByRole('button', { name: '모두 지우기' }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '모두 지우기 확인' }));
    });
    expect(clearSoul).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('아직 기억한 것이 없어요. 대화를 나누면 여기에 쌓입니다.')).toBeTruthy();
  });

  it('shows the empty state, with no 모두 지우기 when there is nothing to clear', async () => {
    vi.mocked(fetchSoul).mockResolvedValueOnce({ user_md: '', markdown: '', memories: [] });
    await renderPanel();
    expect(screen.getByText('아직 기억한 것이 없어요. 대화를 나누면 여기에 쌓입니다.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '모두 지우기' })).toBeNull();
  });

  it('offers 모두 지우기 when only the profile text exists', async () => {
    vi.mocked(fetchSoul).mockResolvedValueOnce({ user_md: '대학원생이에요.', markdown: '', memories: [] });
    await renderPanel();
    expect(screen.getByRole('button', { name: '모두 지우기' })).toBeTruthy();
  });

  it('offers a retry when the memory cannot be loaded', async () => {
    vi.mocked(fetchSoul).mockRejectedValueOnce(new Error('500'));
    render(<SoulPanel />);
    expect((await screen.findByRole('alert')).textContent).toContain('기억을 불러오지 못했어요.');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '다시 불러오기' })); });
    expect(await screen.findByText('요약은 짧게')).toBeTruthy();
  });
});
