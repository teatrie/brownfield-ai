/**
 * Status transition dropdown for epic lifecycle state changes.
 *
 * Renders a select dropdown showing the current status and valid
 * next states. On selection, calls the status update API and
 * notifies the parent via callback.
 */

import { useState } from 'react';
import { updateEpicStatus } from '../api/client';

/** Props for the StatusTransition component. */
interface StatusTransitionProps {
  /** The epic identifier to update. */
  epicId: string;
  /** The current lifecycle status of the epic. */
  currentStatus: string;
  /** Array of valid status values the epic may transition to. */
  validTransitions: string[];
  /** Callback invoked after a successful status change. */
  onStatusChange: (newStatus: string) => void;
}

/**
 * Format a status string for display in the dropdown.
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
 * Dropdown selector for transitioning an epic to a valid next state.
 *
 * Displays the current status as a disabled option and each valid
 * transition as a selectable option. On selection, persists the
 * change via the API and notifies the parent component.
 *
 * @param props - Component props with epic ID, current status, and transitions.
 * @returns A styled select element with transition options.
 */
export function StatusTransition({
  epicId,
  currentStatus,
  validTransitions,
  onStatusChange,
}: StatusTransitionProps): React.JSX.Element {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  /**
   * Handle dropdown value change by persisting the new status.
   *
   * @param event - The select change event.
   */
  async function handleChange(event: React.ChangeEvent<HTMLSelectElement>): Promise<void> {
    const newStatus = event.target.value;
    if (!newStatus || newStatus === currentStatus) return;

    setSaving(true);
    setError(null);
    try {
      await updateEpicStatus(epicId, newStatus);
      setToast(`Status changed to ${formatStatus(newStatus)}`);
      onStatusChange(newStatus);
      setTimeout(() => setToast(null), 3000);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to update status';
      setError(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="status-transition">
      <select
        value=""
        onChange={handleChange}
        disabled={saving || validTransitions.length === 0}
        aria-label="Change epic status"
      >
        <option value="" disabled>
          {formatStatus(currentStatus)}
        </option>
        {validTransitions.map((status) => (
          <option key={status} value={status}>
            {formatStatus(status)}
          </option>
        ))}
      </select>
      {error && <span className="status-transition__error">{error}</span>}
      {toast && <span className="toast">{toast}</span>}
    </div>
  );
}
