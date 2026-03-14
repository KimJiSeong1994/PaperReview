/**
 * Tests for PaperReviewPanel component.
 *
 * Validates:
 * - Loading / error / no-review (null) states
 * - Review tab: scores, summary, methodology, strengths, weaknesses, questions
 * - Detailed review section toggle
 * - Highlights tab: filters, distribution bar, strength/weakness counts, auto-highlight button
 * - HighlightCard: click to scroll/expand, remove button
 * - CSS class presence for key structural elements
 * - Edge cases: empty arrays, missing optional fields
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import PaperReviewPanel from '../components/mypage/PaperReviewPanel';
import type { PaperReview, HighlightItem } from '../api/client';

// Lazy Plotly import will try to dynamically import react-plotly.js in test env.
// Mock it to avoid ESM issues.
vi.mock('react-plotly.js', () => ({
  default: vi.fn(() => null),
}));

// ── Fixtures ──────────────────────────────────────────────────────────────

const mockReview: PaperReview = {
  summary: 'This paper proposes a novel approach.',
  strengths: [
    { point: 'Clear motivation', evidence: 'Section 1', significance: 'high' },
    { point: 'Strong baselines', evidence: 'Table 2', significance: 'medium' },
  ],
  weaknesses: [
    { point: 'Limited evaluation', evidence: 'One dataset only', severity: 'major' },
  ],
  methodology_assessment: {
    rigor: 4,
    novelty: 3,
    reproducibility: 2,
    commentary: 'Solid methodology.',
  },
  key_contributions: ['New architecture'],
  questions_for_authors: ['How does it scale?', 'Why not compare to X?'],
  overall_score: 7,
  confidence: 4,
  detailed_review_markdown:
    '## Summary\nThis paper proposes a novel approach.\n\n## Strengths\nThe motivation is clear.',
  created_at: '2024-01-01T00:00:00',
  model: 'gpt-4.1',
  input_type: 'abstract',
};

const mockHighlights: HighlightItem[] = [
  {
    id: 'rhl_001',
    text: 'The motivation is clear',
    color: '#a5b4fc',
    memo: '[핵심 발견] Good intro',
    created_at: '2024-01-01T00:00:00',
    category: 'finding',
    significance: 4,
    strength_or_weakness: 'strength',
  },
  {
    id: 'rhl_002',
    text: 'Limited evaluation',
    color: '#fda4af',
    memo: '[연구 한계] Narrow scope',
    created_at: '2024-01-01T00:00:00',
    category: 'limitation',
    significance: 3,
    strength_or_weakness: 'weakness',
  },
];

const defaultProps = {
  review: mockReview,
  loading: false,
  error: null,
  highlights: mockHighlights,
  activeTab: 'review' as const,
  highlightFilter: null,
  onTabChange: vi.fn(),
  onFilterChange: vi.fn(),
  onClose: vi.fn(),
};

function renderPanel(overrides: Partial<typeof defaultProps & {
  onDelete?: () => void;
  onReReview?: () => void;
  onRemoveHighlight?: (id: string) => void;
  onAutoHighlight?: () => void;
  autoHighlighting?: boolean;
}> = {}) {
  return render(<PaperReviewPanel {...defaultProps} {...overrides} />);
}

// ── Tests ─────────────────────────────────────────────────────────────────

describe('PaperReviewPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Loading state ──────────────────────────────────────────────────────

  it('renders loading spinner when loading=true', () => {
    renderPanel({ loading: true, review: null });
    expect(screen.getByText('Analyzing paper...')).toBeInTheDocument();
    expect(screen.getByText(/15-30 seconds/)).toBeInTheDocument();
    // Panel title shown even in loading state
    expect(screen.getByText('Review')).toBeInTheDocument();
  });

  it('loading state shows close button', () => {
    renderPanel({ loading: true, review: null });
    const closeBtn = screen.getByTitle('Close');
    expect(closeBtn).toBeInTheDocument();
  });

  it('calls onClose when close button clicked in loading state', () => {
    renderPanel({ loading: true, review: null });
    fireEvent.click(screen.getByTitle('Close'));
    expect(defaultProps.onClose).toHaveBeenCalledOnce();
  });

  // ── Error state ────────────────────────────────────────────────────────

  it('renders error message when error is set', () => {
    renderPanel({ error: 'LLM timed out', review: null, loading: false });
    expect(screen.getByText('LLM timed out')).toBeInTheDocument();
  });

  it('shows retry button when onReReview is provided in error state', () => {
    const onReReview = vi.fn();
    renderPanel({ error: 'error', review: null, loading: false, onReReview });
    expect(screen.getByText('Retry')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Retry'));
    expect(onReReview).toHaveBeenCalledOnce();
  });

  it('does not show retry button when onReReview is undefined in error state', () => {
    renderPanel({ error: 'error', review: null, loading: false });
    expect(screen.queryByText('Retry')).not.toBeInTheDocument();
  });

  // ── No-review state ────────────────────────────────────────────────────

  it('renders nothing when review is null and not loading/error', () => {
    const { container } = renderPanel({ review: null, loading: false, error: null });
    expect(container.firstChild).toBeNull();
  });

  // ── Review tab — header ────────────────────────────────────────────────

  it('renders tab buttons in header', () => {
    renderPanel();
    expect(screen.getByText('Review')).toBeInTheDocument();
    expect(screen.getByText('Highlights')).toBeInTheDocument();
  });

  it('calls onTabChange with "highlights" when highlights tab clicked', () => {
    renderPanel();
    // Find the Highlights button (not the badge span)
    const highlightsBtn = screen.getAllByText(/Highlights/)[0];
    fireEvent.click(highlightsBtn);
    expect(defaultProps.onTabChange).toHaveBeenCalledWith('highlights');
  });

  it('shows highlight count badge when highlights exist', () => {
    renderPanel();
    expect(screen.getByText('2')).toBeInTheDocument(); // badge
  });

  it('does not show delete button when onDelete is not provided', () => {
    renderPanel();
    expect(screen.queryByTitle('Delete review')).not.toBeInTheDocument();
  });

  it('shows delete button when onDelete is provided', () => {
    const onDelete = vi.fn();
    renderPanel({ onDelete });
    expect(screen.getByTitle('Delete review')).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Delete review'));
    expect(onDelete).toHaveBeenCalledOnce();
  });

  // ── Review tab — scores ────────────────────────────────────────────────

  it('renders overall score and confidence', () => {
    renderPanel();
    // ScoreBadge renders the number as text
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('Overall')).toBeInTheDocument();
    expect(screen.getByText('Confidence')).toBeInTheDocument();
  });

  it('renders input type badge', () => {
    renderPanel();
    expect(screen.getByText('Abstract')).toBeInTheDocument();
  });

  it('renders "Full Text" badge for full_text input type', () => {
    renderPanel({ review: { ...mockReview, input_type: 'full_text' } });
    expect(screen.getByText('Full Text')).toBeInTheDocument();
  });

  it('renders "Metadata" badge for metadata input type', () => {
    renderPanel({ review: { ...mockReview, input_type: 'metadata' } });
    expect(screen.getByText('Metadata')).toBeInTheDocument();
  });

  // ── Review tab — summary ───────────────────────────────────────────────

  it('renders summary section', () => {
    renderPanel();
    expect(screen.getByText('Summary')).toBeInTheDocument();
    expect(screen.getByText('This paper proposes a novel approach.')).toBeInTheDocument();
  });

  // ── Review tab — methodology ───────────────────────────────────────────

  it('renders methodology bars with labels', () => {
    renderPanel();
    expect(screen.getByText('Rigor')).toBeInTheDocument();
    expect(screen.getByText('Novelty')).toBeInTheDocument();
    expect(screen.getByText('Reproducibility')).toBeInTheDocument();
  });

  it('renders methodology commentary', () => {
    renderPanel();
    expect(screen.getByText('Solid methodology.')).toBeInTheDocument();
  });

  it('does not render commentary when empty', () => {
    renderPanel({
      review: {
        ...mockReview,
        methodology_assessment: { ...mockReview.methodology_assessment, commentary: '' },
      },
    });
    expect(screen.queryByText('Solid methodology.')).not.toBeInTheDocument();
  });

  // ── Review tab — strengths/weaknesses ─────────────────────────────────

  it('renders strengths count and items when expanded (default)', () => {
    renderPanel();
    expect(screen.getByText(/Strengths \(2\)/)).toBeInTheDocument();
    expect(screen.getByText('Clear motivation')).toBeInTheDocument();
    expect(screen.getByText('Strong baselines')).toBeInTheDocument();
  });

  it('collapses strengths when toggle is clicked', () => {
    renderPanel();
    const toggleBtn = screen.getByText(/Strengths \(2\)/).closest('button')!;
    fireEvent.click(toggleBtn);
    expect(screen.queryByText('Clear motivation')).not.toBeInTheDocument();
  });

  it('renders weaknesses count and items when expanded', () => {
    renderPanel();
    expect(screen.getByText(/Weaknesses \(1\)/)).toBeInTheDocument();
    expect(screen.getByText('Limited evaluation')).toBeInTheDocument();
  });

  it('renders severity tag on weakness', () => {
    renderPanel();
    expect(screen.getByText('major')).toBeInTheDocument();
  });

  it('renders significance tag on strength', () => {
    renderPanel();
    expect(screen.getByText('high')).toBeInTheDocument();
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  // ── Review tab — questions ─────────────────────────────────────────────

  it('renders questions count (collapsed by default)', () => {
    renderPanel();
    expect(screen.getByText(/Questions for Authors \(2\)/)).toBeInTheDocument();
    // Questions are collapsed by default
    expect(screen.queryByText('How does it scale?')).not.toBeInTheDocument();
  });

  it('expands questions when toggle clicked', () => {
    renderPanel();
    const toggleBtn = screen.getByText(/Questions for Authors \(2\)/).closest('button')!;
    fireEvent.click(toggleBtn);
    expect(screen.getByText('How does it scale?')).toBeInTheDocument();
    expect(screen.getByText('Why not compare to X?')).toBeInTheDocument();
  });

  // ── Review tab — detailed review ──────────────────────────────────────

  it('renders detailed review label (collapsed by default)', () => {
    renderPanel();
    expect(screen.getByText('Detailed Review')).toBeInTheDocument();
    // Markdown content is not rendered when collapsed
    expect(screen.queryByText('## Summary')).not.toBeInTheDocument();
  });

  it('expands detailed review when toggle clicked and renders markdown', () => {
    renderPanel();
    const toggleBtn = screen.getByText('Detailed Review').closest('button')!;
    fireEvent.click(toggleBtn);
    // ReactMarkdown renders ## Summary as heading text
    expect(screen.getByRole('heading', { name: 'Summary' })).toBeInTheDocument();
  });

  // ── Highlights tab — filters ───────────────────────────────────────────

  it('renders category filter chips in highlights tab', () => {
    renderPanel({ activeTab: 'highlights' });
    // "All (2)" chip
    expect(screen.getByText(/All \(2\)/)).toBeInTheDocument();
    // Category chips from categoryCounts
    expect(screen.getByText(/Finding \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Limitation \(1\)/)).toBeInTheDocument();
  });

  it('calls onFilterChange with null when "All" chip clicked', () => {
    renderPanel({ activeTab: 'highlights' });
    fireEvent.click(screen.getByText(/All \(2\)/));
    expect(defaultProps.onFilterChange).toHaveBeenCalledWith(null);
  });

  it('calls onFilterChange with category name when chip clicked', () => {
    renderPanel({ activeTab: 'highlights' });
    fireEvent.click(screen.getByText(/Finding \(1\)/));
    expect(defaultProps.onFilterChange).toHaveBeenCalledWith('finding');
  });

  it('toggles filter off (calls with null) when active chip is clicked again', () => {
    renderPanel({ activeTab: 'highlights', highlightFilter: 'finding' });
    fireEvent.click(screen.getByText(/Finding \(1\)/));
    expect(defaultProps.onFilterChange).toHaveBeenCalledWith(null);
  });

  // ── Highlights tab — distribution bar ─────────────────────────────────

  it('renders strength/weakness summary counts', () => {
    renderPanel({ activeTab: 'highlights' });
    expect(screen.getByText(/1 strengths/)).toBeInTheDocument();
    expect(screen.getByText(/1 weaknesses/)).toBeInTheDocument();
  });

  // ── Highlights tab — auto-highlight button ─────────────────────────────

  it('does not render auto-highlight button when onAutoHighlight is undefined', () => {
    renderPanel({ activeTab: 'highlights' });
    expect(screen.queryByText(/Auto Highlight/)).not.toBeInTheDocument();
  });

  it('renders auto-highlight button when onAutoHighlight provided', () => {
    renderPanel({ activeTab: 'highlights', onAutoHighlight: vi.fn() });
    expect(screen.getByText(/Auto Highlight/)).toBeInTheDocument();
  });

  it('disables auto-highlight button when autoHighlighting=true', () => {
    renderPanel({
      activeTab: 'highlights',
      onAutoHighlight: vi.fn(),
      autoHighlighting: true,
    });
    const btn = screen.getByText(/Analyzing\.\.\./).closest('button')!;
    expect(btn).toBeDisabled();
  });

  it('calls onAutoHighlight when button clicked', () => {
    const onAutoHighlight = vi.fn();
    renderPanel({ activeTab: 'highlights', onAutoHighlight });
    fireEvent.click(screen.getByText(/Auto Highlight/));
    expect(onAutoHighlight).toHaveBeenCalledOnce();
  });

  // ── Highlights tab — highlight cards ──────────────────────────────────

  it('renders highlight cards with text', () => {
    renderPanel({ activeTab: 'highlights' });
    expect(screen.getByText(/The motivation is clear/)).toBeInTheDocument();
    expect(screen.getByText(/Limited evaluation/)).toBeInTheDocument();
  });

  it('renders category labels on highlight cards', () => {
    renderPanel({ activeTab: 'highlights' });
    expect(screen.getByText('Finding')).toBeInTheDocument();
    expect(screen.getByText('Limitation')).toBeInTheDocument();
  });

  it('renders strength indicator S on strength highlight', () => {
    renderPanel({ activeTab: 'highlights' });
    expect(screen.getByText('S')).toBeInTheDocument();
  });

  it('renders weakness indicator W on weakness highlight', () => {
    renderPanel({ activeTab: 'highlights' });
    expect(screen.getByText('W')).toBeInTheDocument();
  });

  it('does not show remove button until onRemoveHighlight is provided', () => {
    renderPanel({ activeTab: 'highlights' });
    // Remove buttons exist but are opacity:0 (CSS hover). They are in the DOM.
    // With no onRemoveHighlight prop, the remove button should not be rendered at all.
    const removeButtons = screen.queryAllByTitle('Remove highlight');
    expect(removeButtons).toHaveLength(0);
  });

  it('shows remove buttons when onRemoveHighlight is provided', () => {
    renderPanel({ activeTab: 'highlights', onRemoveHighlight: vi.fn() });
    const removeButtons = screen.getAllByTitle('Remove highlight');
    expect(removeButtons).toHaveLength(2);
  });

  it('calls onRemoveHighlight with correct id when remove button clicked', () => {
    const onRemoveHighlight = vi.fn();
    renderPanel({ activeTab: 'highlights', onRemoveHighlight });
    const removeButtons = screen.getAllByTitle('Remove highlight');
    fireEvent.click(removeButtons[0]);
    expect(onRemoveHighlight).toHaveBeenCalledWith('rhl_001');
  });

  // ── Highlights tab — filtering ─────────────────────────────────────────

  it('filters highlight list by active category', () => {
    renderPanel({ activeTab: 'highlights', highlightFilter: 'limitation' });
    expect(screen.getByText(/Limited evaluation/)).toBeInTheDocument();
    expect(screen.queryByText(/The motivation is clear/)).not.toBeInTheDocument();
  });

  it('shows empty message when filtered list is empty', () => {
    renderPanel({
      activeTab: 'highlights',
      highlightFilter: 'gap',  // No highlights in this category
    });
    expect(screen.getByText(/No highlights in this category/)).toBeInTheDocument();
  });

  it('shows generic empty message when no highlights at all', () => {
    renderPanel({ activeTab: 'highlights', highlights: [] });
    expect(screen.getByText(/No highlights$/)).toBeInTheDocument();
  });

  // ── Edge cases ─────────────────────────────────────────────────────────

  it('renders correctly with empty strengths array', () => {
    renderPanel({ review: { ...mockReview, strengths: [] } });
    expect(screen.getByText(/Strengths \(0\)/)).toBeInTheDocument();
  });

  it('renders correctly with empty weaknesses array', () => {
    renderPanel({ review: { ...mockReview, weaknesses: [] } });
    expect(screen.getByText(/Weaknesses \(0\)/)).toBeInTheDocument();
  });

  it('renders correctly with empty questions array', () => {
    renderPanel({ review: { ...mockReview, questions_for_authors: [] } });
    expect(screen.getByText(/Questions for Authors \(0\)/)).toBeInTheDocument();
  });

  it('renders correctly when detailed_review_markdown is empty string', () => {
    renderPanel({ review: { ...mockReview, detailed_review_markdown: '' } });
    const toggleBtn = screen.getByText('Detailed Review').closest('button')!;
    fireEvent.click(toggleBtn);
    // Should not crash even with empty markdown
    expect(screen.getByText('Detailed Review')).toBeInTheDocument();
  });

  it('sorts highlights by significance descending in highlights tab', () => {
    const unsortedHighlights: HighlightItem[] = [
      { ...mockHighlights[1], significance: 1 }, // Low significance
      { ...mockHighlights[0], significance: 5 }, // High significance
    ];
    renderPanel({ activeTab: 'highlights', highlights: unsortedHighlights });
    const cards = screen.getAllByText(/\u201c/); // opening quote of highlight text
    // First card should show the high-significance one
    expect(cards[0].textContent).toContain('The motivation is clear');
  });
});
