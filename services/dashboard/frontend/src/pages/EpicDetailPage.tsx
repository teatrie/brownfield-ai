/**
 * Epic detail page showing metadata, artifact timeline, TODOs,
 * PR references, and the lifecycle state machine.
 *
 * Fetches full epic detail from the API using the URL parameter,
 * and renders a two-panel layout: artifact timeline on the left,
 * sidebar with TODOs, PRs, and state machine on the right.
 */

import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { fetchEpicDetail, updateEpicPriority } from '../api/client';
import { ArtifactCard } from '../components/ArtifactCard';
import { PriorityEditor } from '../components/PriorityEditor';
import { PrRefEditor } from '../components/PrRefEditor';
import { StateMachine } from '../components/StateMachine';
import { StatusTransition } from '../components/StatusTransition';
import { TodoItemRow } from '../components/TodoItem';
import { useToast } from '../hooks/useToast';
import type { EpicDetailResponse, EpicStatus } from '../types';
import { VALID_TRANSITIONS } from '../types';
import { formatDateHeader, groupArtifactsByDate } from '../utils/date';
import { InfoTip } from '../components/InfoTip';
import { ViewModeToggle } from '../components/ViewModeToggle';
import { SECTION_TIPS } from '../utils/tooltips';

/**
 * Format an ISO-8601 timestamp to a short readable date.
 *
 * @param timestamp - ISO-8601 date string.
 * @returns Locale-formatted short date.
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
 * Epic detail page with artifact timeline and sidebar panels.
 *
 * Reads the epic ID from URL params, fetches full detail from the
 * API, and renders a metadata header, left-panel artifact timeline
 * grouped by date, and right-panel sidebar with linked TODOs,
 * PR references, and the lifecycle state machine.
 *
 * @returns The epic detail page element.
 */
export function EpicDetailPage(): React.JSX.Element {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<EpicDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const [exporting, setExporting] = useState(false);

  /**
   * Re-fetch epic detail data and update state.
   *
   * Used as a callback after write-action mutations to refresh
   * the page with the latest server state.
   */
  const refreshData = useCallback(() => {
    if (!id) return;
    fetchEpicDetail(id)
      .then((response) => {
        setData(response);
      })
      .catch(() => {
        /* Refresh errors are non-blocking; stale data is acceptable. */
      });
  }, [id]);

  useEffect(() => {
    if (!id) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchEpicDetail(id)
      .then((response) => {
        if (!cancelled) {
          setData(response);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Failed to fetch epic detail';
          setError(message);
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
  }, [id]);

  if (loading) {
    return <div className="loading">Loading epic detail...</div>;
  }

  if (error) {
    return <div className="error-message">{error}</div>;
  }

  if (!data) {
    return <div className="error-message">Epic not found.</div>;
  }

  const { epic, artifacts, context } = data;

  const sortedArtifacts = [...artifacts].sort(
    (a, b) => new Date(b.metadata.timestamp).getTime() - new Date(a.metadata.timestamp).getTime(),
  );
  const dateGroups = groupArtifactsByDate(sortedArtifacts);

  return (
    <div className="epic-detail">
      <Link to="/epics" className="back-link">&larr; Back to Epics</Link>
      <div className="epic-detail__header">
        <span className="epic-detail__id mono">{epic.epic_id}</span>
        <StatusTransition
          epicId={epic.epic_id}
          currentStatus={epic.status}
          validTransitions={data.valid_transitions}
          onStatusChange={() => refreshData()}
        />
        <PriorityEditor
          value={epic.priority}
          onSave={async (p) => {
            await updateEpicPriority(epic.epic_id, p);
            showToast(`Priority updated to P${p}`);
            refreshData();
          }}
        />
        {epic.claimed_by && (
          <span className="epic-detail__claimed">
            Claimed by <strong>{epic.claimed_by}</strong>
          </span>
        )}
        <span className="epic-detail__dates mono">
          Created {formatDate(epic.created_at)} | Updated {formatDate(epic.last_updated_at)}
        </span>
        <button
          className="epic-detail__export-btn"
          disabled={exporting}
          onClick={async () => {
            setExporting(true);
            try {
              const res = await fetch(`/api/epics/${encodeURIComponent(epic.epic_id)}/export`);
              if (!res.ok) {
                showToast('Export failed');
                return;
              }
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `${epic.epic_id}.zip`;
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 100);
            } catch (err) {
              console.error('Export failed:', err);
              showToast('Export failed');
            } finally {
              setExporting(false);
            }
          }}
        >
          {exporting ? 'Exporting...' : 'Download All'}
        </button>
      </div>

      <h1 className="epic-detail__title">{epic.title}</h1>

      <div className="epic-detail__panels">
        <div className="epic-detail__left">
          <div className="epic-detail__section">
            <h2 className="epic-detail__section-title">Artifact Timeline</h2>
            {sortedArtifacts.length === 0 && (
              <p className="epic-detail__empty">No artifacts recorded yet.</p>
            )}
            {Array.from(dateGroups.entries()).map(([dateKey, groupArtifacts]) => (
              <div key={dateKey} className="date-group">
                <div className="date-group__header">
                  <h3 className="date-group__label">{formatDateHeader(dateKey)}</h3>
                  <ViewModeToggle />
                </div>
                {groupArtifacts.map((artifact) => (
                  <ArtifactCard key={artifact.id} artifact={artifact} />
                ))}
              </div>
            ))}
          </div>
        </div>

        <div className="epic-detail__right">
          <div className="epic-detail__section">
            <h2 className="epic-detail__section-title">Linked TODOs <InfoTip text={SECTION_TIPS.linked_todos} /></h2>
            {context.open_todos.length === 0 && (
              <p className="epic-detail__empty">No open TODOs.</p>
            )}
            {context.open_todos.map((todo) => (
              <TodoItemRow key={todo.id} todo={todo} onUpdate={refreshData} />
            ))}
          </div>

          <div className="epic-detail__section">
            <h2 className="epic-detail__section-title">Pull Requests <InfoTip text={SECTION_TIPS.pull_requests} /></h2>
            <PrRefEditor
              epicId={epic.epic_id}
              currentPrs={epic.current_prs}
              onUpdate={() => refreshData()}
            />
          </div>

          <div className="epic-detail__section">
            <h2 className="epic-detail__section-title">State Machine <InfoTip text={SECTION_TIPS.state_machine} /></h2>
            <StateMachine
              currentStatus={epic.status as EpicStatus}
              transitions={VALID_TRANSITIONS}
            />
          </div>
        </div>
      </div>

      {toast && <span className="toast">{toast}</span>}
    </div>
  );
}
