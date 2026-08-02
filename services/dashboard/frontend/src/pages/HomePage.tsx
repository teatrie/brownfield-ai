/**
 * Dashboard home page displaying aggregated stats for epics, TODOs, and activity.
 *
 * Fetches data from GET /api/stats/home on mount and renders three
 * stat sections with clickable cards linking to filtered list views.
 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchHomeStats } from '../api/client';
import type { HomeStats } from '../types';

/**
 * Format a status key for display (e.g. "in_progress" -> "In Progress").
 *
 * @param status - Raw status string with underscores.
 * @returns Title-cased display string.
 */
function formatStatus(status: string): string {
  return status
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Ordered list of epic statuses for the stat card grid. */
const EPIC_STATUS_ORDER = [
  'in_progress',
  'in_review',
  'approved',
  'pending',
  'backlog',
  'completed',
  'blocked',
  'abandoned',
] as const;

/**
 * Dashboard home page component.
 *
 * Renders three sections: Epic stats, TODO stats, and Activity stats.
 * Each stat card links to the relevant filtered list view.
 */
export function HomePage(): React.JSX.Element {
  const [stats, setStats] = useState<HomeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchHomeStats()
      .then((data) => {
        if (!cancelled) {
          setStats(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load stats');
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <div className="home-page__loading">Loading stats...</div>;
  }

  if (error || !stats) {
    return <div className="home-page__error">{error || 'Failed to load stats'}</div>;
  }

  return (
    <div className="home-page">
      <div className="home-page__header">
        <h1 className="home-page__title">Dashboard</h1>
        <p className="home-page__subtitle">Overview of epics, TODOs, and recent activity</p>
      </div>

      {/* Epic Stats Section */}
      <section className="stat-section">
        <div className="stat-section__header">
          <span className="stat-section__icon" aria-hidden="true">{'\uD83D\uDCCB'}</span>
          <h2 className="stat-section__title">Epics</h2>
        </div>
        <div className="stat-cards">
          <Link to="/epics" className="stat-card stat-card--accent">
            <span className="stat-card__value">{stats.epics.total}</span>
            <span className="stat-card__label">Total</span>
          </Link>
          <Link to="/epics?status=in_progress" className="stat-card stat-card--status-in_progress">
            <span className="stat-card__value">{stats.epics.active}</span>
            <span className="stat-card__label">Active</span>
          </Link>
          <Link to="/epics?status=blocked" className="stat-card stat-card--status-blocked">
            <span className="stat-card__value">{stats.epics.blocked}</span>
            <span className="stat-card__label">Blocked</span>
          </Link>
          <Link to="/epics?status=completed" className="stat-card stat-card--success">
            <span className="stat-card__value">{stats.epics.completed_24h}</span>
            <span className="stat-card__label">Completed 24h</span>
          </Link>
          {EPIC_STATUS_ORDER.map((status) => (
            <Link
              key={status}
              to={`/epics?status=${status}`}
              className={`stat-card stat-card--status-${status}`}
            >
              <span className="stat-card__value">
                {stats.epics.by_status[status] ?? 0}
              </span>
              <span className="stat-card__label">{formatStatus(status)}</span>
            </Link>
          ))}
        </div>
      </section>

      {/* TODO Stats Section */}
      <section className="stat-section">
        <div className="stat-section__header">
          <span className="stat-section__icon" aria-hidden="true">{'\u2714\uFE0F'}</span>
          <h2 className="stat-section__title">TODOs</h2>
        </div>
        <div className="stat-cards">
          <Link to="/todos?status=all" className="stat-card stat-card--accent">
            <span className="stat-card__value">{stats.todos.total}</span>
            <span className="stat-card__label">Total</span>
          </Link>
          <Link to="/todos?status=open" className="stat-card stat-card--status-in_progress">
            <span className="stat-card__value">{stats.todos.open}</span>
            <span className="stat-card__label">Open</span>
          </Link>
          <Link to="/todos?status=assigned" className="stat-card stat-card--status-approved">
            <span className="stat-card__value">{stats.todos.assigned}</span>
            <span className="stat-card__label">Assigned</span>
          </Link>
          <Link to="/todos?status=done" className="stat-card stat-card--success">
            <span className="stat-card__value">{stats.todos.done}</span>
            <span className="stat-card__label">Done</span>
          </Link>
          <Link to="/todos?status=open&sort=priority&order=asc" className="stat-card stat-card--warn">
            <span className="stat-card__value">{stats.todos.high_priority_open}</span>
            <span className="stat-card__label">High Priority</span>
          </Link>
        </div>
        {stats.todos.by_category.length > 0 && (
          <div className="home-page__category-list">
            {stats.todos.by_category.map((cat) => (
              <Link
                key={cat.category}
                to={`/todos?status=open&category=${encodeURIComponent(cat.category)}`}
                className="home-page__category-tag"
              >
                {cat.category}
                <span className="home-page__category-count">{cat.count}</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Activity Stats Section */}
      <section className="stat-section">
        <div className="stat-section__header">
          <span className="stat-section__icon" aria-hidden="true">{'\u23F3'}</span>
          <h2 className="stat-section__title">Activity</h2>
        </div>
        {stats.activity === null ? (
          <div className="home-page__error">
            Activity data unavailable (ChromaDB unreachable)
          </div>
        ) : (
          <div className="stat-cards">
            <Link to="/timeline/all" className="stat-card stat-card--accent">
              <span className="stat-card__value">{stats.activity.artifacts_24h}</span>
              <span className="stat-card__label">Artifacts 24h</span>
            </Link>
            <Link to="/timeline/all" className="stat-card stat-card--muted">
              <span className="stat-card__value">{stats.activity.artifacts_1h}</span>
              <span className="stat-card__label">Artifacts 1h</span>
            </Link>
            <Link to="/timeline/all" className="stat-card stat-card--success">
              <span className="stat-card__value">{stats.activity.gates_24h.pass}</span>
              <span className="stat-card__label">Gates Pass 24h</span>
            </Link>
            <Link to="/timeline/all" className="stat-card stat-card--warn">
              <span className="stat-card__value">{stats.activity.gates_24h.fail}</span>
              <span className="stat-card__label">Gates Fail 24h</span>
            </Link>
            <Link to="/timeline/all" className="stat-card stat-card--accent">
              <span className="stat-card__value">{stats.activity.prs_created_7d}</span>
              <span className="stat-card__label">PRs Created 7d</span>
            </Link>
            <Link to="/timeline/all" className="stat-card stat-card--success">
              <span className="stat-card__value">{stats.activity.prs_merged_7d}</span>
              <span className="stat-card__label">PRs Merged 7d</span>
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
