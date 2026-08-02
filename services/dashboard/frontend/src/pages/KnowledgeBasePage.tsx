/**
 * Knowledge Base browser page for ChromaDB document collections.
 *
 * Allows browsing documents in a selected collection with pagination,
 * semantic search within the collection, and click-to-expand detail
 * views showing full content and metadata.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchKbCollections,
  fetchKbDocuments,
  searchKb,
} from '../api/client';
import type {
  KbCollection,
  KbDocument,
  KbSearchResult,
} from '../types';

/** Number of documents to fetch per page. */
const PAGE_SIZE = 20;

/** Sentinel value for the "all collections" pseudo-option. */
const ALL_COLLECTIONS = '__all__';

/** Human-friendly display names for KB collection identifiers. */
const COLLECTION_LABELS: Record<string, string> = {
  long_term_document: 'Documents',
  chat_history: 'Chat History',
};

/** Document tagged with its source collection for unique keying. */
type TaggedDocument = KbDocument & { _collection: string };

/** Search result tagged with its source collection for unique keying. */
type TaggedSearchResult = KbSearchResult & { _collection: string };

/** Truncate text to a maximum length with ellipsis. */
function truncate(text: string, maxLen: number): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
}

/** Render metadata as a key-value table. */
function renderMetadata(metadata: Record<string, unknown>): React.JSX.Element {
  const entries = Object.entries(metadata);
  if (entries.length === 0) {
    return <p className="kb-page__meta-empty">No metadata</p>;
  }
  return (
    <table className="kb-page__meta-table">
      <thead>
        <tr>
          <th>Key</th>
          <th>Value</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key}>
            <td className="kb-page__meta-key">{key}</td>
            <td className="kb-page__meta-value">
              {typeof value === 'string' ? value : JSON.stringify(value)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Knowledge Base browser page with collection selector, search, and
 * paginated document list with click-to-expand detail.
 *
 * @returns The Knowledge Base page element.
 */
export function KnowledgeBasePage(): React.JSX.Element {
  const [collections, setCollections] = useState<KbCollection[]>([]);
  const [activeCollection, setActiveCollection] = useState<string>(ALL_COLLECTIONS);
  const [documents, setDocuments] = useState<TaggedDocument[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [offset, setOffset] = useState<number>(0);

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchResults, setSearchResults] = useState<TaggedSearchResult[]>([]);
  const [isSearchMode, setIsSearchMode] = useState<boolean>(false);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  /** Load the list of available collections on mount. */
  useEffect(() => {
    void (async () => {
      try {
        const data = await fetchKbCollections();
        setCollections([...data.collections].sort((a, b) => b.count - a.count));
      } catch {
        // Collection list failure is non-fatal
      }
    })();
  }, []);

  /** Collection names to query (all real collections, or just the active one). */
  const targetCollections = useMemo(
    () =>
      activeCollection === ALL_COLLECTIONS
        ? collections.map((c) => c.name)
        : [activeCollection],
    [activeCollection, collections],
  );

  /** Fetch documents for the active collection(s). */
  const loadDocuments = useCallback(
    async (currentOffset: number, append: boolean) => {
      if (targetCollections.length === 0) {
        setDocuments([] as TaggedDocument[]);
        setTotal(0);
        setHasMore(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const results = await Promise.all(
          targetCollections.map(async (name) => {
            const data = await fetchKbDocuments({ collection: name, limit: PAGE_SIZE, offset: currentOffset });
            return {
              documents: data.documents.map((doc) => ({ ...doc, _collection: name })),
              total: data.total,
              has_more: data.has_more,
            };
          }),
        );
        const merged = results.flatMap((r) => r.documents);
        const totalCount = results.reduce((sum, r) => sum + r.total, 0);
        const anyMore = results.some((r) => r.has_more);
        setDocuments((prev) => (append ? [...prev, ...merged] : merged));
        setTotal(totalCount);
        setHasMore(anyMore);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load documents.');
      } finally {
        setLoading(false);
      }
    },
    [targetCollections],
  );

  /** Reload documents when collection changes. */
  useEffect(() => {
    setOffset(0);
    setIsSearchMode(false);
    setSearchQuery('');
    setSearchResults([] as TaggedSearchResult[]);
    setExpandedId(null);
    void loadDocuments(0, false);
  }, [loadDocuments]);

  /** Load more documents (append). */
  const handleLoadMore = useCallback(() => {
    const nextOffset = offset + PAGE_SIZE;
    setOffset(nextOffset);
    void loadDocuments(nextOffset, true);
  }, [offset, loadDocuments]);

  /** Execute KB search. */
  const handleSearch = useCallback(async () => {
    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setIsSearchMode(false);
      return;
    }
    setLoading(true);
    setError(null);
    setIsSearchMode(true);
    setExpandedId(null);
    try {
      const results = await Promise.all(
        targetCollections.map(async (name) => {
          const data = await searchKb(trimmed, name);
          return data.results.map((r) => ({ ...r, _collection: name }));
        }),
      );
      const merged = results
        .flat()
        .sort((a, b) => a.distance - b.distance);
      setSearchResults(merged);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed.');
      setSearchResults([] as TaggedSearchResult[]);
    } finally {
      setLoading(false);
    }
  }, [searchQuery, targetCollections]);

  /** Handle Enter key in search input. */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        void handleSearch();
      }
    },
    [handleSearch],
  );

  /** Handle collection change. */
  const handleCollectionChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      setActiveCollection(e.target.value);
    },
    [],
  );

  /** Toggle document detail expansion. */
  const toggleExpand = useCallback((compositeId: string) => {
    setExpandedId((prev) => (prev === compositeId ? null : compositeId));
  }, []);

  /** Clear search and return to browse mode. */
  const handleClearSearch = useCallback(() => {
    setSearchQuery('');
    setIsSearchMode(false);
    setSearchResults([] as TaggedSearchResult[]);
    setExpandedId(null);
  }, []);

  return (
    <div className="kb-page">
      <h1 className="kb-page__title">Knowledge Base</h1>

      <div className="kb-page__filters">
        <select
          value={activeCollection}
          onChange={handleCollectionChange}
          aria-label="Select collection"
        >
          {collections.length > 0
            ? (
                <>
                  <option value={ALL_COLLECTIONS}>
                    All ({collections.reduce((s, c) => s + c.count, 0)})
                  </option>
                  {collections.map((c) => (
                    <option key={c.name} value={c.name}>
                      {COLLECTION_LABELS[c.name] ?? c.name} ({c.count})
                    </option>
                  ))}
                </>
              )
            : (
                <>
                  <option value={ALL_COLLECTIONS}>All</option>
                  <option value="long_term_document">Documents</option>
                  <option value="chat_history">Chat History</option>
                </>
              )}
        </select>

        <div className="kb-page__search-bar">
          <div className="kb-page__search-input-wrap">
            <input
              type="text"
              placeholder="Semantic search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              aria-label="Search documents"
            />
            {searchQuery && (
              <button
                type="button"
                className="kb-page__input-clear"
                onClick={handleClearSearch}
                aria-label="Clear search"
              >
                {'\u00D7'}
              </button>
            )}
          </div>
          <button type="button" onClick={() => void handleSearch()}>
            Search
          </button>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading && documents.length === 0 && searchResults.length === 0 && (
        <div className="loading">Loading...</div>
      )}

      {/* Browse mode */}
      {!isSearchMode && (
        <>
          <span className="kb-page__count">{total} document(s)</span>

          {!loading && documents.length === 0 && !error && (
            <div className="kb-page__empty">No documents in this collection.</div>
          )}

          {documents.map((doc) => (
            <div
              key={`${doc._collection}:${doc.id}`}
              className={`kb-page__row ${expandedId === `${doc._collection}:${doc.id}` ? 'kb-page__row--expanded' : ''}`}
              onClick={() => toggleExpand(`${doc._collection}:${doc.id}`)}
              role="button"
              tabIndex={0}
              aria-expanded={expandedId === `${doc._collection}:${doc.id}`}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  toggleExpand(`${doc._collection}:${doc.id}`);
                }
              }}
            >
              <div className="kb-page__row-summary">
                <code className="kb-page__doc-id">{truncate(doc.id, 8)}</code>
                <span className="kb-page__doc-preview">{truncate(doc.document, 120)}</span>
                <span className="kb-page__meta-count">
                  {Object.keys(doc.metadata).length} key(s)
                </span>
              </div>
              {expandedId === `${doc._collection}:${doc.id}` && (
                <div className="kb-page__detail">
                  <h3>Content</h3>
                  <pre className="kb-page__content">{doc.document}</pre>
                  <h3>Metadata</h3>
                  {renderMetadata(doc.metadata)}
                </div>
              )}
            </div>
          ))}

          {loading && documents.length > 0 && <div className="loading">Loading...</div>}

          {hasMore && !loading && (
            <button type="button" className="load-more-btn" onClick={handleLoadMore}>
              Load more
            </button>
          )}
        </>
      )}

      {/* Search mode */}
      {isSearchMode && (
        <>
          {!loading && searchResults.length === 0 && !error && (
            <div className="kb-page__empty">No results found.</div>
          )}

          {searchResults.map((result) => (
            <div
              key={`${result._collection}:${result.id}`}
              className={`kb-page__row ${expandedId === `${result._collection}:${result.id}` ? 'kb-page__row--expanded' : ''}`}
              onClick={() => toggleExpand(`${result._collection}:${result.id}`)}
              role="button"
              tabIndex={0}
              aria-expanded={expandedId === `${result._collection}:${result.id}`}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  toggleExpand(`${result._collection}:${result.id}`);
                }
              }}
            >
              <div className="kb-page__row-summary">
                <code className="kb-page__doc-id">{truncate(result.id, 8)}</code>
                <span className="kb-page__doc-preview">{truncate(result.document, 120)}</span>
                <span className="kb-page__distance">d={result.distance.toFixed(3)}</span>
              </div>
              {expandedId === `${result._collection}:${result.id}` && (
                <div className="kb-page__detail">
                  <h3>Content</h3>
                  <pre className="kb-page__content">{result.document}</pre>
                  <h3>Metadata</h3>
                  {renderMetadata(result.metadata)}
                </div>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
