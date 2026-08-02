/**
 * Polymorphic search result card for the unified search page.
 *
 * Renders differently based on the result source (artifact, todo, or
 * epic), displaying source-specific badges, metadata, and navigation
 * links.  Query terms are highlighted in the document snippet using
 * ``<mark>`` elements.
 */

import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { fetchTodoById } from '../api/client';
import type { TodoItem } from '../types';

/** Props for the SearchResult component. */
interface SearchResultProps {
  /** Source collection the result belongs to. */
  source: 'artifact' | 'todo' | 'epic';
  /** Unique identifier within the source collection. */
  id: string;
  /** Full document text content. */
  document: string;
  /** Metadata fields from the source collection. */
  metadata: Record<string, unknown>;
  /** Vector distance from the query (lower is more relevant). */
  distance: number;
  /** The original search query for highlighting. */
  query: string;
}

/**
 * Highlight occurrences of query terms in text using ``<mark>`` elements.
 *
 * Splits the query into words and wraps each case-insensitive match
 * in the text with a ``<mark>`` tag.  Non-matching segments are
 * rendered as plain text nodes.
 *
 * @param text - The text to highlight within.
 * @param query - The search query whose words should be highlighted.
 * @returns An array of React nodes with highlighted matches.
 */
function highlightTerms(text: string, query: string): React.ReactNode[] {
  if (!query.trim()) return [text];

  const words = query
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0);
  if (words.length === 0) return [text];

  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'i');
  const parts = text.split(pattern);

  // split(capturing_group) places matches at odd indices
  return parts.map((part, i) => {
    if (i % 2 === 1) {
      return <mark key={i}>{part}</mark>;
    }
    return part;
  });
}

/**
 * Compute a human-readable label for the result source.
 *
 * @param source - Source identifier string.
 * @returns Display label (e.g. "Artifact", "TODO", "Epic").
 */
function sourceLabel(source: string): string {
  if (source === 'artifact') return 'Artifact';
  if (source === 'todo') return 'TODO';
  if (source === 'epic') return 'Epic';
  return source;
}

/**
 * Compute a relevance percentage from the vector distance.
 *
 * Maps distance 0 to 100% and distance >= 2 to 0%, clamped
 * between 0 and 100.
 *
 * @param distance - Vector distance value.
 * @returns Integer percentage (0-100).
 */
function relevancePercent(distance: number): number {
  return Math.max(0, Math.min(100, Math.round((1 - distance / 2) * 100)));
}

/**
 * Polymorphic search result card.
 *
 * Renders a card with source label, relevance indicator, document
 * snippet with highlighted query terms, and metadata.  Artifact and
 * epic results are clickable and navigate to their detail views.
 * TODO results are not clickable.
 *
 * @param props - Search result properties.
 * @returns A styled search result card element.
 */
export function SearchResult({
  source,
  id,
  document,
  metadata,
  distance,
  query,
}: SearchResultProps): React.JSX.Element {
  const navigate = useNavigate();
  const snippet = document.length > 200 ? document.slice(0, 200) + '...' : document;
  const relevance = relevancePercent(distance);

  const [expanded, setExpanded] = useState(false);
  const [todoDetail, setTodoDetail] = useState<TodoItem | null>(null);
  const [todoLoading, setTodoLoading] = useState(false);
  const [todoError, setTodoError] = useState<string | null>(null);

  const isTodo = source === 'todo';

  const handleToggle = useCallback(async () => {
    setExpanded((prev) => !prev);
    if (!todoDetail && !todoLoading) {
      setTodoLoading(true);
      setTodoError(null);
      try {
        const detail = await fetchTodoById(Number(id));
        setTodoDetail(detail);
      } catch (err) {
        setTodoError(err instanceof Error ? err.message : 'Failed to load TODO');
      } finally {
        setTodoLoading(false);
      }
    }
  }, [id, todoDetail, todoLoading]);

  const handleClick = useCallback(() => {
    sessionStorage.setItem('lastSearchQuery', query);
    if (source === 'artifact') {
      const epicId = (metadata.epic_id as string) || 'all';
      navigate(`/timeline/${epicId}?artifact=${encodeURIComponent(id)}`);
    } else if (source === 'epic') {
      navigate(`/epics/${id}`);
    }
  }, [source, id, metadata, navigate, query]);

  const isClickable = source === 'artifact' || source === 'epic';

  return (
    <div
      className={`search-result ${isClickable ? 'search-result--clickable' : ''}${isTodo ? ` search-result--expandable${expanded ? ' search-result--expanded' : ''}` : ''}`}
      onClick={isClickable ? handleClick : isTodo ? handleToggle : undefined}
      role={isClickable || isTodo ? 'button' : undefined}
      tabIndex={isClickable || isTodo ? 0 : undefined}
      onKeyDown={
        isClickable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') handleClick();
            }
          : isTodo
            ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleToggle();
                }
              }
            : undefined
      }
      aria-expanded={isTodo ? expanded : undefined}
    >
      <div className="search-result__header">
        <span className={`search-result__source search-result__source--${source}`}>
          {sourceLabel(source)}
        </span>
        <span className="search-result__id mono">{id}</span>
        <div className="search-result__distance" title={`Relevance: ${relevance}%`}>
          <div
            className="search-result__distance-bar"
            style={{ width: `${relevance}%` }}
          />
        </div>
      </div>

      {source === 'artifact' && (
        <div className="search-result__badges">
          {metadata.artifact_type ? (
            <span className="artifact-card__type">
              {String(metadata.artifact_type).replace(/_/g, ' ')}
            </span>
          ) : null}
          {metadata.verdict ? (
            <span className="artifact-card__verdict artifact-card__verdict--neutral">
              {String(metadata.verdict)}
            </span>
          ) : null}
        </div>
      )}

      {source === 'todo' && (
        <div className="search-result__badges">
          <span
            className={`todo-item__dot todo-item__dot--${String(metadata.status || 'open')}`}
          />
          {metadata.category ? (
            <span className="todo-item__category">{String(metadata.category)}</span>
          ) : null}
        </div>
      )}

      {source === 'epic' && (
        <div className="search-result__badges">
          {metadata.status ? (
            <span className={`status-badge status-badge--${String(metadata.status)}`}>
              {String(metadata.status)}
            </span>
          ) : null}
        </div>
      )}

      <div className="search-result__snippet">
        {highlightTerms(snippet, query)}
      </div>

      <div className="search-result__meta mono">
        {metadata.timestamp ? <span>{String(metadata.timestamp)}</span> : null}
        {metadata.last_updated_at ? <span>{String(metadata.last_updated_at)}</span> : null}
        {metadata.status && source !== 'epic' ? <span>{String(metadata.status)}</span> : null}
      </div>

      {isTodo && expanded && (
        <div className="search-result__detail">
          {todoLoading && <div className="loading">Loading...</div>}
          {todoError && <div className="error-message">{todoError}</div>}
          {todoDetail && (
            <>
              {todoDetail.description && (
                <p className="search-result__detail-description">{todoDetail.description}</p>
              )}
              <div className="search-result__detail-meta">
                <span className="search-result__detail-meta-label">Status</span>
                <span>{todoDetail.status}</span>
                {todoDetail.epic_id && (
                  <>
                    <span className="search-result__detail-meta-label">Epic</span>
                    <Link to={`/epics/${todoDetail.epic_id}`} className="todo-item__epic-link mono">
                      {todoDetail.epic_id}
                    </Link>
                  </>
                )}
                {todoDetail.created_at && (
                  <>
                    <span className="search-result__detail-meta-label">Created</span>
                    <span className="mono">{new Date(todoDetail.created_at).toLocaleString()}</span>
                  </>
                )}
                {todoDetail.last_updated_at && (
                  <>
                    <span className="search-result__detail-meta-label">Updated</span>
                    <span className="mono">{new Date(todoDetail.last_updated_at).toLocaleString()}</span>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
