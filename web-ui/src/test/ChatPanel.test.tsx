import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ChatPanel from '../components/mypage/ChatPanel';
import { createRef } from 'react';

const defaultProps = {
  messages: [],
  inputValue: '',
  setInputValue: vi.fn(),
  isStreaming: false,
  streamingContent: '',
  chatEndRef: createRef<HTMLDivElement>(),
  chatTopicFilter: 'all',
  setChatTopicFilter: vi.fn(),
  allTopics: ['ML', 'NLP'],
  selectedCount: 0,
  onSendMessage: vi.fn(),
  onKeyDown: vi.fn(),
  onClearChat: vi.fn(),
  processCitationChildren: vi.fn((children) => children),
  handleCitationClick: vi.fn(),
};

describe('ChatPanel', () => {
  it('renders welcome message when no messages', () => {
    render(<ChatPanel {...defaultProps} />);
    expect(screen.getByText('Ask about your bookmarked papers')).toBeInTheDocument();
  });

  it.skip('renders topic filter select with all options', () => {
    render(<ChatPanel {...defaultProps} />);
    const select = screen.getByRole('combobox');
    expect(select).toBeInTheDocument();
    expect(screen.getByText('All topics')).toBeInTheDocument();
    expect(screen.getByText('ML')).toBeInTheDocument();
    expect(screen.getByText('NLP')).toBeInTheDocument();
  });

  it('renders user and assistant messages', () => {
    const messages = [
      { role: 'user' as const, content: 'Hello test question' },
      { role: 'assistant' as const, content: 'Test response' },
    ];
    render(<ChatPanel {...defaultProps} messages={messages} />);
    expect(screen.getByText('Hello test question')).toBeInTheDocument();
    expect(screen.getByText('Test response')).toBeInTheDocument();
  });

  it('disables send button when input is empty', () => {
    render(<ChatPanel {...defaultProps} />);
    const sendBtn = screen.getByLabelText('Send message');
    expect(sendBtn).toBeDisabled();
  });

  it('shows typing indicator when streaming without content', () => {
    render(<ChatPanel {...defaultProps} isStreaming={true} streamingContent="" />);
    const typingDots = document.querySelector('.mypage-chat-typing');
    expect(typingDots).toBeInTheDocument();
  });

  it('shows selected bookmark count in welcome when checkboxes checked', () => {
    render(<ChatPanel {...defaultProps} selectedCount={3} />);
    expect(screen.getByText(/Chatting with 3 selected bookmarks/)).toBeInTheDocument();
  });

  it('shows "Selected (N)" in topic dropdown when bookmarks selected', () => {
    render(<ChatPanel {...defaultProps} selectedCount={2} />);
    expect(screen.getByText('Selected (2)')).toBeInTheDocument();
  });
});
