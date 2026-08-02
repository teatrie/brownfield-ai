/**
 * Global search bar for the dashboard header.
 *
 * Renders a text input with a keyboard-shortcut hint.  Pressing Enter
 * navigates to the search page with the query as a URL parameter.
 * When already on the search page the input stays in sync with the
 * URL ``q`` parameter so it acts as the sole search input for the
 * entire application.  The Cmd+K shortcut focuses the input from
 * anywhere.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

/**
 * Header search bar that navigates to the search page on submit.
 *
 * Supports Cmd+K (Mac) / Ctrl+K (other) global keyboard shortcut
 * to focus the input.  Pressing Enter triggers navigation to
 * ``/search?q=<query>``.  On the search page the input reflects
 * the current URL query and updates it on submit.
 *
 * @returns The search bar element.
 */
export function SearchBar(): React.JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const inputRef = useRef<HTMLInputElement>(null);
  const isOnSearchPage = location.pathname === '/search';

  const urlQuery = searchParams.get('q') || '';
  const [query, setQuery] = useState(urlQuery);

  // Keep the input in sync with the URL q param (e.g. browser back/forward).
  useEffect(() => {
    if (isOnSearchPage) {
      setQuery(urlQuery);
    }
  }, [urlQuery, isOnSearchPage]);

  /** Navigate to the search page with the current query. */
  const handleSubmit = useCallback(() => {
    const trimmed = query.trim();
    if (trimmed) {
      navigate(`/search?q=${encodeURIComponent(trimmed)}`);
    }
  }, [query, navigate]);

  /** Handle keydown in the input field. */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  useEffect(() => {
    /** Global keyboard shortcut handler for Cmd+K / Ctrl+K. */
    const handleGlobalKeyDown = (e: KeyboardEvent): void => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handleGlobalKeyDown);
    return () => document.removeEventListener('keydown', handleGlobalKeyDown);
  }, []);

  return (
    <div className="search-bar">
      <input
        ref={inputRef}
        type="text"
        className="search-input"
        placeholder="Search... (Cmd+K)"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
      />
      {query && (
        <button
          className="search-bar__clear"
          onClick={() => {
            setQuery('');
            if (isOnSearchPage) {
              navigate('/search');
            }
            inputRef.current?.focus();
          }}
          aria-label="Clear search"
        >
          {'\u00D7'}
        </button>
      )}
    </div>
  );
}
