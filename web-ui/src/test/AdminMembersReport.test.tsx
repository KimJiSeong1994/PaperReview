import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import AdminMembersReport from '../components/AdminMembersReport';
import type { AdminUser } from '../api/client';

vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  fetchAdminSoulStats: vi.fn(() => new Promise(() => {})),
}));

const SELF: AdminUser = {
  username: 'alice', role: 'admin', created_at: '2025-01-01T00:00:00Z', bookmark_count: 0,
  conversation_count: 3, last_conversation_at: '2026-11-02T09:00:00+00:00',
  memory_count: 5, profile_updated_at: '2026-11-01T09:00:00+00:00',
};
const OTHER: AdminUser = {
  username: 'bob', role: 'user', created_at: '2025-03-15T00:00:00Z', bookmark_count: 2,
  conversation_count: 0, last_conversation_at: null, memory_count: 0, profile_updated_at: null,
};

function renderReport(overrides: Partial<Parameters<typeof AdminMembersReport>[0]> = {}) {
  return render(<AdminMembersReport users={[SELF, OTHER]} loading={false}
    currentUsername="alice" onToggleRole={vi.fn()} onDeleteUser={vi.fn()} {...overrides} />);
}
const member = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name},`) });
const rows = () => screen.getAllByRole('button', { expanded: false }).map((el) => el.getAttribute('aria-label')?.split(',')[0]);
const choose = (name: string, value: string) => fireEvent.change(screen.getByRole('combobox', { name }), { target: { value } });

describe('AdminMembersReport — current accounts', () => {
  it('shows account activity without retired counts, filters or detail sections', () => {
    renderReport();
    expect(member('alice')).toHaveAccessibleName('alice, 권한 admin, 대화 3, 메모리 5');
    fireEvent.click(member('bob'));
    expect(screen.getByText(/대화 0개/)).toHaveTextContent('메모리 0개');
    expect(screen.getByText(/연구 프로필 갱신 없음/)).toBeInTheDocument();
    for (const label of ['북마크', '커리큘럼', '수집 논문', '계정 없는 잔여 기록만', '북마크 많은 순', '논문 많은 순', '커리큘럼 많은 순']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it('keeps self protection and named sibling action controls', () => {
    const onToggleRole = vi.fn();
    const onDeleteUser = vi.fn();
    renderReport({ onToggleRole, onDeleteUser });
    expect(screen.getByRole('button', { name: 'alice 권한 해제' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'alice 계정 삭제' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'bob 권한 승격' }));
    fireEvent.click(screen.getByRole('button', { name: 'bob 계정 삭제' }));
    expect(onToggleRole).toHaveBeenCalledWith('bob', 'user');
    expect(onDeleteUser).toHaveBeenCalledWith('bob');
    expect(within(member('bob')).queryByRole('button')).not.toBeInTheDocument();
    expect(member('bob')).toHaveAttribute('aria-expanded', 'false');
  });

  it('expands an accessible account panel and switches directly between members', () => {
    renderReport();
    fireEvent.click(member('alice'));
    expect(member('alice')).toHaveAttribute('aria-expanded', 'true');
    const id = member('alice').getAttribute('aria-controls')!;
    expect(document.getElementById(id)).toHaveTextContent('대화 3개');
    expect(document.getElementById(id)).toHaveTextContent('메모리 5개');
    fireEvent.click(member('bob'));
    expect(document.getElementById(id)).not.toBeInTheDocument();
    expect(member('bob')).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(member('bob'));
    expect(member('bob')).toHaveAttribute('aria-expanded', 'false');
  });

  it('searches case insensitively and restores the roster after an empty result', () => {
    renderReport();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'BO' } });
    expect(rows()).toEqual(['bob']);
    expect(screen.getByRole('status')).toHaveTextContent('2명 중 1명');
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'missing' } });
    expect(screen.getByText('조건에 맞는 회원이 없습니다.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검색·필터 초기화' }));
    expect(rows()).toEqual(['alice', 'bob']);
  });

  it('filters admins and sorts by signup or recent conversation with stable ties', () => {
    renderReport();
    choose('목록 범위', 'admin');
    expect(rows()).toEqual(['alice']);
    choose('목록 범위', 'all');
    choose('정렬 기준', 'joined');
    expect(rows()).toEqual(['bob', 'alice']);
    choose('정렬 기준', 'conversation');
    expect(rows()).toEqual(['alice', 'bob']);
  });

  it('shows loading and empty states', () => {
    const view = renderReport({ loading: true });
    expect(screen.getByText('회원 정보를 불러오는 중...')).toBeInTheDocument();
    view.rerender(<AdminMembersReport users={[]} loading={false} currentUsername="alice"
      onToggleRole={vi.fn()} onDeleteUser={vi.fn()} />);
    expect(screen.getByText('회원 데이터가 없습니다.')).toBeInTheDocument();
  });
});
