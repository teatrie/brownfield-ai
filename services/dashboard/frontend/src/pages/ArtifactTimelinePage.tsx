/**
 * Artifact timeline page with filters and real-time updates.
 *
 * Displays a chronological list of artifacts for a given epic,
 * grouped by date, with filter controls for artifact type, wave,
 * domain, and verdict. Supports real-time updates via WebSocket
 * and expanding an artifact to a full detail view.
 */

import { useCallback, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { fetchArtifactDetail, fetchArtifactTimeline, fetchEpics } from '../api/client';
import type { FetchTimelineParams } from '../api/client';
import { ArtifactCard } from '../components/ArtifactCard';
import { ArtifactDetail } from '../components/ArtifactDetail';
import { EpicStatusBadge } from '../components/EpicStatusBadge';
import { TimelineFilter } from '../components/TimelineFilter';
import type { TimelineFilters } from '../components/TimelineFilter';
import { useLiveTimeline } from '../hooks/useLiveTimeline';
import type { Artifact, Epic } from '../types';
import { formatDateHeader, groupArtifactsByDate } from '../utils/date';
import { ViewModeToggle } from '../components/ViewModeToggle';

/** Number of artifacts to fetch per page. */
const PAGE_SIZE = 50;

/**
 * Epic picker shown on the /timeline/all route.
 *
 * Fetches all epics on mount and renders a clickable list of rows,
 * each linking to the per-epic timeline view.
 *
 * @returns The epic picker element.
 */
function EpicPicker(): React.JSX.Element {
  const [epics, setEpics] = useState<Epic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchEpics({ limit: 200 })
      .then((data) => {
        if (!cancelled) {
          setEpics(data.epics);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to fetch epics');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <div className="loading">Loading epics...</div>;
  }

  if (error) {
    return <div className="error-message">{error}</div>;
  }

  if (epics.length === 0) {
    return <div className="epic-list__empty">No epics found.</div>;
  }

  return (
    <div className="epic-list">
      <div className="epic-list__rows">
        {epics.map((epic) => (
          <Link
            key={epic.epic_id}
            to={`/timeline/${epic.epic_id}`}
            className="epic-list__row"
          >
            <EpicStatusBadge status={epic.status} />
            <span className="epic-list__id mono">{epic.epic_id}</span>
            <span className="epic-list__title">{epic.title}</span>
            <span className="priority-pill">P{epic.priority}</span>
            {epic.claimed_by && (
              <span className="epic-list__claimed">{epic.claimed_by}</span>
            )}
            <span className="epic-list__date mono">
              {(() => {
                try {
                  return new Date(epic.last_updated_at).toLocaleDateString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                  });
                } catch {
                  return epic.last_updated_at;
                }
              })()}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

/**
 * Artifact timeline page with filters, pagination, and live updates.
 *
 * Reads the ``epicId`` from URL params. If the epicId is "all",
 * shows a prompt to select an epic. Otherwise fetches and displays
 * the artifact timeline with filter controls and real-time WebSocket
 * updates. Clicking an artifact shows the full detail view.
 *
 * @returns The artifact timeline page element.
 */
export function ArtifactTimelinePage(): React.JSX.Element {
  const { epicId } = useParams<{ epicId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [filters, setFilters] = useState<TimelineFilters>({
    artifactType: '',
    wave: '',
    domain: '',
    verdict: '',
  });

  const { newArtifacts, clearNew } = useLiveTimeline(
    epicId && epicId !== 'all' ? epicId : null,
  );

  /** Load artifacts from the API with current filters. */
  const loadArtifacts = useCallback(
    async (currentOffset: number, append: boolean) => {
      if (!epicId || epicId === 'all') return;

      setLoading(true);
      setError(null);

      try {
        const params: FetchTimelineParams = {
          limit: PAGE_SIZE,
          offset: currentOffset,
        };
        if (filters.artifactType) {
          params.artifact_type = filters.artifactType;
        }
        if (filters.wave) {
          params.wave = filters.wave;
        }
        if (filters.domain) {
          params.domain = filters.domain;
        }
        if (filters.verdict) {
          params.verdict = filters.verdict;
        }

        const data = await fetchArtifactTimeline(epicId, params);
        setArtifacts((prev) => (append ? [...prev, ...data.artifacts] : data.artifacts));
        setHasMore(data.has_more);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to fetch artifacts';
        setError(message);
      } finally {
        setLoading(false);
      }
    },
    [epicId, filters],
  );

  // Reload when epicId or filters change
  useEffect(() => {
    setOffset(0);
    setSelectedArtifact(null);
    clearNew();
    void loadArtifacts(0, false);
  }, [epicId, filters, loadArtifacts, clearNew]);

  // Auto-open artifact from ?artifact= query param (e.g. from search results)
  useEffect(() => {
    const artifactId = searchParams.get('artifact');
    if (!artifactId) return;
    // Clear the param so back navigation doesn't re-trigger
    setSearchParams({}, { replace: true });
    fetchArtifactDetail(artifactId)
      .then((artifact) => setSelectedArtifact(artifact))
      .catch(() => { /* Artifact not found — stay on timeline */ });
  }, [searchParams, setSearchParams]);

  /** Handle filter changes from the filter bar. */
  const handleFilterChange = useCallback((newFilters: TimelineFilters) => {
    setFilters(newFilters);
  }, []);

  /** Handle clicking "Load more" for pagination. */
  const handleLoadMore = useCallback(() => {
    const newOffset = offset + PAGE_SIZE;
    setOffset(newOffset);
    void loadArtifacts(newOffset, true);
  }, [offset, loadArtifacts]);

  /** Handle clicking an artifact to show its detail view. */
  const handleArtifactClick = useCallback((artifact: Artifact) => {
    setSelectedArtifact(artifact);
  }, []);

  /** Handle closing the artifact detail view. */
  const handleDetailClose = useCallback(() => {
    setSelectedArtifact(null);
  }, []);

  // Show epic picker for the /timeline/all route
  if (!epicId || epicId === 'all') {
    return (
      <div className="timeline-page">
        <h1 className="timeline-page__title">Select an Epic</h1>
        <EpicPicker />
      </div>
    );
  }

  // Show detail view when an artifact is selected
  if (selectedArtifact) {
    return (
      <div className="timeline-page">
        <button className="back-link" onClick={handleDetailClose}>&larr; Back to Timeline</button>
        <ArtifactDetail artifact={selectedArtifact} onClose={handleDetailClose} />
      </div>
    );
  }

  // Combine live artifacts with fetched artifacts
  const allArtifacts = [...newArtifacts, ...artifacts];
  const dateGroups = groupArtifactsByDate(allArtifacts);

  return (
    <div className="timeline-page">
      <Link to="/timeline/all" className="back-link">&larr; Back to Timeline</Link>
      <h1 className="timeline-page__title">
        Timeline: <span className="mono">{epicId}</span>
      </h1>

      <TimelineFilter filters={filters} onFilterChange={handleFilterChange} />

      {error && <div className="error-message">{error}</div>}

      {newArtifacts.length > 0 && (
        <div className="timeline-page__live-badge">
          {newArtifacts.length} new artifact{newArtifacts.length !== 1 ? 's' : ''}
        </div>
      )}

      {!loading && !error && allArtifacts.length === 0 && (
        <div className="epic-list__empty">No artifacts found.</div>
      )}

      <div className="timeline-page__list">
        {Array.from(dateGroups.entries()).map(([dateKey, groupArtifacts]) => (
          <div key={dateKey} className="date-group">
            <div className="date-group__header">
              <h3 className="date-group__label">{formatDateHeader(dateKey)}</h3>
              <ViewModeToggle />
            </div>
            {groupArtifacts.map((artifact) => (
              <div
                key={artifact.id}
                onClick={() => handleArtifactClick(artifact)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    handleArtifactClick(artifact);
                  }
                }}
              >
                <ArtifactCard artifact={artifact} />
              </div>
            ))}
          </div>
        ))}
      </div>

      {loading && <div className="loading">Loading artifacts...</div>}

      {hasMore && !loading && (
        <button className="load-more-btn" onClick={handleLoadMore}>
          Load more
        </button>
      )}
    </div>
  );
}
