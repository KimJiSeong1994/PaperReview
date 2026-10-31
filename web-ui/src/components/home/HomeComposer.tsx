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
      <label htmlFor="home-query" className="home-sr-only">검색어</label>
      <textarea
        id="home-query"
        ref={textareaRef}
        rows={2}
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
          <span aria-hidden="true">📎</span> PDF 열기
        </Link>
        <button
          type="submit"
          className="home-send"
          aria-label="논문 검색"
          disabled={!query.trim()}
        >
          <span aria-hidden="true">↑</span>
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
