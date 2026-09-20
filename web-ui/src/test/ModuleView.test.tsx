import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import ModuleView from '../components/curriculum/ModuleView';
import type { CurriculumModule } from '../components/curriculum/types';

const module: CurriculumModule = {
  id: 'm1', week: 1, title: 'Attention', description: 'Week one',
  topics: [{
    id: 't1', title: 'Transformers',
    papers: [{ id: 'p1', title: 'Attention Is All You Need', authors: ['Vaswani'], year: 2017, venue: 'NeurIPS', category: 'required', context: 'The starting point.' }],
  }],
};
const props = {
  module, readPapers: new Set<string>(), selectedPaperId: null,
  onSelectPaper: vi.fn(), onToggleRead: vi.fn(), getModuleProgress: () => ({ read: 0, total: 1 }),
};

beforeEach(() => vi.clearAllMocks());

describe('ModuleView paper card', () => {
  it('opens a paper from the keyboard and exposes the read mark as a checkbox', () => {
    render(<ModuleView {...props} />);
    const card = screen.getByRole('button', { name: 'Attention Is All You Need 열기' });
    expect(card).toHaveAttribute('tabindex', '0');
    fireEvent.keyDown(card, { key: 'Enter' });
    expect(props.onSelectPaper).toHaveBeenCalledWith('p1');

    const read = screen.getByRole('checkbox', { name: 'Attention Is All You Need 읽음 표시' });
    expect(read).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(read);
    expect(props.onToggleRead).toHaveBeenCalledWith('p1');
    // The mark is not nested inside any button-role element.
    expect(read.closest('[role="button"]')).toBeNull();
    expect(card.querySelector('[role="checkbox"]')).toBeNull();
  });
});
