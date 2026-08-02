/**
 * Unified semantic search page for the ledger dashboard.
 *
 * Displays scope tabs (All / Artifacts / TODOs / Epics) and a ranked
 * list of search results.  The query is driven entirely by the ``q``
 * URL parameter, which the header SearchBar component sets on Enter.
 */

import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { searchAll } from '../api/client';
import type { SearchResultItem } from '../api/client';
import { SearchResult } from '../components/SearchResult';

/** Available search scope options. */
const SCOPES: Array<{ value: string; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'artifacts', label: 'Artifacts' },
  { value: 'todos', label: 'TODOs' },
  { value: 'epics', label: 'Epics' },
];

/** Sort order options for search results. */
type SortOrder = 'relevance' | 'date';

/**
 * Extract a sortable timestamp from a search result's metadata.
 *
 * @param metadata - Result metadata record.
 * @returns ISO timestamp string, or empty string if absent.
 */
function getTimestamp(metadata: Record<string, unknown>): string {
  const ts = metadata.timestamp;
  return typeof ts === 'string' ? ts : '';
}

/**
 * Semantic search page with scope filtering and result rendering.
 *
 * Reads the ``q`` query parameter from the URL, provides scope tabs
 * to narrow results, and renders a ranked list of SearchResult cards.
 * The header SearchBar is the sole input — this page has no input of
 * its own.
 *
 * @returns The search page element.
 */
export function SearchPage(): React.JSX.Element {
  const [searchParams] = useSearchParams();
  const query = searchParams.get('q') || '';

  const [activeScope, setActiveScope] = useState('all');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [sortOrder, setSortOrder] = useState<SortOrder>('relevance');

  /** Execute the search against the API. */
  const executeSearch = useCallback(
    async (q: string, scope: string) => {
      if (!q.trim()) {
        setResults([]);
        setSearched(false);
        return;
      }
      setLoading(true);
      setError(null);
      setSearched(true);
      try {
        const data = await searchAll(q, scope);
        setResults(data.results);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Search failed';
        setError(message);
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  /** Re-run search when the URL query or active scope changes. */
  useEffect(() => {
    void executeSearch(query, activeScope);
  }, [query, activeScope, executeSearch]);

  /** Handle clicking a scope tab. */
  const handleScopeChange = useCallback(
    (scope: string) => {
      setActiveScope(scope);
    },
    [],
  );

  return (
    <div className="search-page">
      <div className="scope-tabs">
        {SCOPES.map((s) => (
          <button
            key={s.value}
            className={`scope-tab ${activeScope === s.value ? 'scope-tab--active' : ''}`}
            onClick={() => handleScopeChange(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading && <div className="loading">Searching...</div>}

      {!loading && searched && results.length === 0 && !error && (
        <div className="search-page__empty">
          No results found for &quot;{query}&quot;.
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="search-results">
          <div className="search-results__sort">
            <button
              className={`scope-tab ${sortOrder === 'relevance' ? 'scope-tab--active' : ''}`}
              onClick={() => setSortOrder('relevance')}
            >
              Relevance
            </button>
            <button
              className={`scope-tab ${sortOrder === 'date' ? 'scope-tab--active' : ''}`}
              onClick={() => setSortOrder('date')}
            >
              Date
            </button>
          </div>
          {[...results]
            .sort((a, b) => {
              if (sortOrder === 'relevance') return 0;
              return getTimestamp(b.metadata).localeCompare(getTimestamp(a.metadata));
            })
            .map((result) => (
            <SearchResult
              key={`${result.source}-${result.id}`}
              source={result.source}
              id={result.id}
              document={result.document}
              metadata={result.metadata}
              distance={result.distance}
              query={query}
            />
          ))}
        </div>
      )}
    </div>
  );
}
