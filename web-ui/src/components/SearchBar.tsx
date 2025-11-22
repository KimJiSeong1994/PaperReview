import { useState } from 'react';
import './SearchBar.css';

interface SearchBarProps {
  onSearch: (query: string) => void;
  loading: boolean;
}

function SearchBar({ onSearch, loading }: SearchBarProps) {
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
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Start typing to search..."
            className="search-input"
            disabled={loading}
          />
          <button 
            type="submit" 
            className="search-submit-button" 
            disabled={loading || !query.trim()}
            title="Search"
          >
            <span className="search-icon">🔍</span>
          </button>
        </div>
      </form>
    </div>
  );
}

export default SearchBar;

