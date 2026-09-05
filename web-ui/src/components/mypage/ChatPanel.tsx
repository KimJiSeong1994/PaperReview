import type React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage, ChatSource } from '../../api/client';

export interface ChatPanelProps {
  messages: ChatMessage[];
  inputValue: string;
  setInputValue: (v: string) => void;
  isStreaming: boolean;
  streamingContent: string;
  chatEndRef: React.RefObject<HTMLDivElement | null>;
  chatTopicFilter: string;
  setChatTopicFilter: (v: string) => void;
  allTopics: string[];
  selectedCount: number;
  onSendMessage: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onClearChat: () => void;
  processCitationChildren: (children: React.ReactNode, sources?: ChatSource[], msgContent?: string) => React.ReactNode;
  handleCitationClick: (source: ChatSource, chatContent: string, refNum: number) => void;
}

export default function ChatPanel({
  messages, inputValue, setInputValue,
  isStreaming, streamingContent,
  chatEndRef,
  chatTopicFilter, setChatTopicFilter, allTopics,
  selectedCount,
  onSendMessage, onKeyDown, onClearChat,
  processCitationChildren, handleCitationClick,
}: ChatPanelProps) {
  return (
    <div className="mypage-chat-panel" role="region" aria-label="논문과 대화">
      {/* Chat header */}
      <div className="mypage-panel-header mypage-chat-header">
        <span>
          {chatTopicFilter === 'all' && selectedCount > 0
            ? `논문과 대화 · ${selectedCount}개 선택됨`
            : '논문과 대화'}
        </span>
        <div className="mypage-chat-header-actions">
          <select className="mypage-chat-topic-select" value={chatTopicFilter}
            onChange={(e) => setChatTopicFilter(e.target.value)}>
            <option value="all">{selectedCount > 0 ? `선택됨 (${selectedCount})` : '전체 주제'}</option>
            {allTopics.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          {messages.length > 0 && (
            <button className="mypage-chat-clear-btn"
              onClick={onClearChat}
              title="Clear chat">✕</button>
          )}
        </div>
      </div>

      <div className="mypage-chat-messages" aria-live="polite">
        {messages.length === 0 && !isStreaming && (
          <div className="mypage-chat-welcome">
            <p className="mypage-chat-welcome-title">북마크한 논문에 대해 물어보세요</p>
            <p className="mypage-chat-welcome-subtitle">
              {chatTopicFilter !== 'all'
                ? `"${chatTopicFilter}" 주제의 논문을 대상으로 답합니다.`
                : selectedCount > 0
                  ? `선택한 북마크 ${selectedCount}개를 대상으로 답합니다. 목록의 체크박스로 대상을 바꿀 수 있습니다.`
                  : '지금은 북마크한 리포트 전체를 대상으로 답합니다. 목록의 체크박스를 켜면 그 북마크들로 범위가 좁혀집니다.'}
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`mypage-chat-message mypage-chat-${msg.role}`}>
            <div className="mypage-chat-bubble">
              {msg.role === 'assistant' ? (
                <div className="mypage-chat-markdown prose-base">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ children }) => {
                        return <p>{processCitationChildren(children, msg.sources, msg.content)}</p>;
                      },
                      li: ({ children }) => {
                        return <li>{processCitationChildren(children, msg.sources, msg.content)}</li>;
                      },
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                  {msg.sources && msg.sources.length > 0 && (
                    <details className="mypage-sources-section">
                      <summary className="mypage-sources-header">Sources ({msg.sources.length})</summary>
                      <div className="mypage-sources-list">
                        {msg.sources.map(source => (
                          <div key={source.ref} className="mypage-source-item"
                            onClick={() => handleCitationClick(source, msg.content, source.ref)}>
                            <span className="mypage-source-ref">[{source.ref}]</span>
                            <span className="mypage-source-title">{source.title}</span>
                            <span className="mypage-source-meta">논문 {source.num_papers}편</span>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              ) : (
                <pre className="mypage-chat-text">{msg.content}</pre>
              )}
            </div>
          </div>
        ))}

        {isStreaming && streamingContent && (
          <div className="mypage-chat-message mypage-chat-assistant">
            <div className="mypage-chat-bubble">
              <div className="mypage-chat-markdown prose-base">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
              </div>
              <span className="mypage-streaming-cursor"></span>
            </div>
          </div>
        )}

        {isStreaming && !streamingContent && (
          <div className="mypage-chat-message mypage-chat-assistant">
            <div className="mypage-chat-bubble">
              <div className="mypage-chat-typing">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      <div className="mypage-chat-input-area">
        <textarea className="mypage-chat-input" value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={chatTopicFilter !== 'all' ? `"${chatTopicFilter}" 논문에 대해 물어보세요...` : selectedCount > 0 ? `선택한 논문 ${selectedCount}편에 대해 물어보세요...` : '북마크한 논문에 대해 물어보세요...'}
          rows={1} disabled={isStreaming} aria-label="Chat message input" />
        <button className="mypage-chat-send" onClick={onSendMessage}
          disabled={isStreaming || !inputValue.trim()} aria-label="Send message">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
