import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

interface HomeComposerProps {
  initialQuery: string;
  onSearch: (query: string) => void;
  guidanceMessage: string | null;
  guidanceSticky: boolean;
  onQueryChange: () => void;
  /** Focus the box on mount (the parent remounts it for "새 검색"). */
  autoFocus?: boolean;
}

/** The home's search box, shaped like a composer: Enter submits, Shift+Enter breaks a line. */
function HomeComposer({
  initialQuery,
  onSearch,
  guidanceMessage,
  guidanceSticky,
  onQueryChange,
  autoFocus = false,
}: HomeComposerProps) {
  const [query, setQuery] = useState(initialQuery);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    const focusOnSlash = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
      if (event.key === '/' && !typing) {
        event.preventDefault();
        textareaRef.current?.focus();
      }
    };
    document.addEventListener('keydown', focusOnSlash);
    return () => document.removeEventListener('keydown', focusOnSlash);
  }, []);

  const submit = () => {
    const trimmed = query.trim();
    if (trimmed) onSearch(trimmed);
  };

  return (
    <form
      className="home-composer"
      onSubmit={(event) => { event.preventDefault(); submit(); }}
    >
      <label htmlFor="home-query" className="home-sr-only">논문 검색</label>
      <textarea
        id="home-query"
        ref={textareaRef}
        rows={1}
        value={query}
        placeholder="논문 검색"
        onChange={(event) => {
          setQuery(event.target.value);
          if (guidanceMessage) onQueryChange();
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
      />
      <div className="home-composer-row">
        <Link className="home-attach" to="/paper-viewer">
          <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
            <path d="M4 1.75h5.25L12.5 5v9.25H4z M9 1.75V5.25h3.5 M6 8.5h4M6 11h4" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          PDF 열기
        </Link>
        <span className="home-composer-hint" aria-hidden="true"><kbd>Enter</kbd> 검색 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 줄바꿈</span>
        <button
          type="submit"
          className="home-send"
          aria-label="논문 검색"
          disabled={!query.trim()}
        >
          검색
          <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
            <path d="M3 8h9.5M9 4.5 12.5 8 9 11.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
      {guidanceMessage && (
        <div className={`search-guidance${guidanceSticky ? ' search-guidance--sticky' : ''}`}>
          {guidanceMessage}
        </div>
      )}
    </form>
  );
}

export default HomeComposer;
