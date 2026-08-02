/**
 * Colored status badge component for epic lifecycle states.
 *
 * Renders a small pill-shaped badge whose background color
 * corresponds to the epic status via CSS custom properties
 * defined in theme.css.
 */

import type { EpicStatus } from '../types';

/** Props for the EpicStatusBadge component. */
interface EpicStatusBadgeProps {
  /** The epic status to display. */
  status: EpicStatus;
}

/**
 * Format a status string for display.
 *
 * Replaces underscores with spaces and converts to title case.
 *
 * @param status - Raw status string (e.g. "in_progress").
 * @returns Formatted display string (e.g. "In Progress").
 */
function formatStatus(status: string): string {
  return status
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Colored pill badge showing an epic's current lifecycle status.
 *
 * Applies a CSS class `status-badge--{status}` that maps to
 * the corresponding `--color-status-*` CSS variable from theme.css.
 *
 * @param props - Component props containing the status value.
 * @returns A styled span element.
 */
export function EpicStatusBadge({ status }: EpicStatusBadgeProps): React.JSX.Element {
  return (
    <span className={`status-badge status-badge--${status}`}>
      {formatStatus(status)}
    </span>
  );
}
