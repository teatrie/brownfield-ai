/**
 * Epic index page listing all epics with status filtering and pagination.
 *
 * Fetches epics from the API on mount, provides filter pills for
 * each status, renders clickable rows for each epic, and supports
 * offset-based "Load more" pagination.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { fetchEpics } from '../api/client';
import { EpicStatusBadge } from '../components/EpicStatusBadge';
import type { Epic, EpicStatus } from '../types';

/** Number of epics to fetch per page. */
const PAGE_SIZE = 25;

/** All status values available as filter options. */
const STATUS_FILTERS: Array<EpicStatus | 'all'> = [
  'all',
  'backlog',
  'pending',
  'approved',
  'in_progress',
  'in_review',
  'completed',
  'blocked',
  'abandoned',
];

/**
 * Format a status filter label for display.
 *
 * Replaces underscores with spaces and converts to title case.
 *
 * @param filter - Raw filter string (e.g. "in_progress" or "all").
 * @returns Formatted display string (e.g. "In Progress" or "All").
 */
function formatFilterLabel(filter: string): string {
  return filter
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Format an ISO-8601 timestamp into a short relative display.
 *
 * @param timestamp - ISO-8601 date string.
 * @returns Locale-formatted short date string.
 */
function formatDate(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return timestamp;
  }
}

/**
 * Epic list page with status filtering and offset-based pagination.
 *
 * Renders filter pills at the top, a list of epic rows with status
 * badges, and a "Load more" button when additional pages exist.
 * Clicking a row navigates to the epic detail view.
 *
 * @returns The epic list page element.
 */
export function EpicListPage(): React.JSX.Element {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialStatus = searchParams.get('status') as EpicStatus | null;
  const [epics, setEpics] = useState<Epic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<EpicStatus | 'all'>(
    initialStatus && STATUS_FILTERS.includes(initialStatus) ? initialStatus : 'all',
  );
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);

  const loadEpics = useCallback(
    async (statusFilter: EpicStatus | 'all', currentOffset: number, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const params = {
          limit: PAGE_SIZE,
          offset: currentOffset,
          ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
        };
        const data = await fetchEpics(params);
        setEpics((prev) => (append ? [...prev, ...data.epics] : data.epics));
        setHasMore(data.has_more);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to fetch epics';
        setError(message);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadEpics(activeFilter, 0, false);
  }, [activeFilter, loadEpics]);

  /** Handle clicking a filter pill. */
  const handleFilterClick = useCallback((filter: EpicStatus | 'all') => {
    setActiveFilter(filter);
    setOffset(0);
  }, []);

  /** Handle clicking the "Load more" button. */
  const handleLoadMore = useCallback(() => {
    const newOffset = offset + PAGE_SIZE;
    setOffset(newOffset);
    void loadEpics(activeFilter, newOffset, true);
  }, [offset, activeFilter, loadEpics]);

  /** Handle clicking an epic row to navigate to its detail page. */
  const handleEpicClick = useCallback(
    (epicId: string) => {
      navigate(`/epics/${epicId}`);
    },
    [navigate],
  );

  return (
    <div className="epic-list">
      <div className="epic-list__filters">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter}
            className={`epic-list__filter ${activeFilter === filter ? 'epic-list__filter--active' : ''}`}
            onClick={() => handleFilterClick(filter)}
          >
            {formatFilterLabel(filter)}
          </button>
        ))}
      </div>

      {error && <div className="error-message">{error}</div>}

      {!loading && !error && epics.length === 0 && (
        <div className="epic-list__empty">No epics found.</div>
      )}

      <div className="epic-list__rows">
        {epics.map((epic) => (
          <div
            key={epic.epic_id}
            className="epic-list__row"
            onClick={() => handleEpicClick(epic.epic_id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                handleEpicClick(epic.epic_id);
              }
            }}
          >
            <EpicStatusBadge status={epic.status} />
            <span className="epic-list__id mono">{epic.epic_id}</span>
            <span className="epic-list__title">{epic.title}</span>
            <span className="priority-pill">P{epic.priority}</span>
            {epic.claimed_by && (
              <span className="epic-list__claimed">{epic.claimed_by}</span>
            )}
            <span className="epic-list__date mono">{formatDate(epic.last_updated_at)}</span>
          </div>
        ))}
      </div>

      {loading && <div className="loading">Loading...</div>}

      {hasMore && !loading && (
        <button className="load-more-btn" onClick={handleLoadMore}>
          Load more
        </button>
      )}
    </div>
  );
}
