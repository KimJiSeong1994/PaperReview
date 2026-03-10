import { useState } from 'react';
import './SearchBar.css';

interface SearchBarProps {
  onSearch: (query: string) => void;
  loading: boolean;
  guidanceMessage?: string | null;
  onQueryChange?: () => void;
}

function SearchBar({ onSearch, loading, guidanceMessage, onQueryChange }: SearchBarProps) {
  const [query, setQuery] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !loading) {
      onSearch(query.trim());
    }
  };

  return (
    <div className="search-bar-container">
      <form onSubmit={handleSubmit} className="search-form">
        <div className="search-input-wrapper">
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (guidanceMessage) onQueryChange?.();
            }}
            placeholder="Search papers..."
            className="search-input"
            disabled={loading}
          />

          <button
            type="submit"
            className="search-submit-button"
            disabled={loading || !query.trim()}
            title="Search"
          >
            <span className="search-icon">&#x1F50D;</span>
          </button>
        </div>
      </form>
      {guidanceMessage && (
        <div className="search-guidance">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          {guidanceMessage}
        </div>
      )}
    </div>
  );
}

export default SearchBar;
