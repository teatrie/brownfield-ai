/**
 * Modal dialog for marking a TODO item as done.
 *
 * Requires the user to provide a resolution note before
 * confirming the action. The resolution text is sent to the
 * API and the parent is notified on success.
 */

import { useState } from 'react';
import { markTodoDone } from '../api/client';

/** Props for the DoneModal component. */
interface DoneModalProps {
  /** The TODO item ID to mark as done. */
  todoId: number;
  /** Callback to close the modal without action. */
  onClose: () => void;
  /** Callback invoked after the TODO is successfully marked done. */
  onDone: () => void;
}

/**
 * Overlay modal requiring a resolution note to mark a TODO as done.
 *
 * Displays a textarea for the resolution note with Cancel and
 * Mark Done buttons. The confirm button is disabled until the
 * user enters a non-empty resolution. On success, calls the
 * onDone callback and closes.
 *
 * @param props - Component props with todo ID and lifecycle callbacks.
 * @returns A fixed-position overlay modal element.
 */
export function DoneModal({
  todoId,
  onClose,
  onDone,
}: DoneModalProps): React.JSX.Element {
  const [resolution, setResolution] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Persist the done status with the resolution note via the API.
   */
  async function handleConfirm(): Promise<void> {
    const trimmed = resolution.trim();
    if (!trimmed) return;
    setSaving(true);
    setError(null);
    try {
      await markTodoDone(todoId, trimmed);
      onDone();
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to mark as done';
      setError(message);
    } finally {
      setSaving(false);
    }
  }

  /**
   * Handle overlay click to close when clicking outside the content.
   *
   * @param event - The mouse click event on the overlay.
   */
  function handleOverlayClick(event: React.MouseEvent<HTMLDivElement>): void {
    if (event.target === event.currentTarget) {
      onClose();
    }
  }

  return (
    <div className="done-modal__overlay" onClick={handleOverlayClick}>
      <div className="done-modal__content">
        <h3 className="done-modal__title">Mark TODO as Done</h3>
        <textarea
          className="done-modal__textarea"
          value={resolution}
          onChange={(e) => setResolution(e.target.value)}
          placeholder="Resolution note (required)..."
          disabled={saving}
          aria-label="Resolution note"
        />
        {error && <p className="done-modal__error">{error}</p>}
        <div className="done-modal__actions">
          <button
            type="button"
            className="done-modal__btn done-modal__btn--cancel"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="done-modal__btn done-modal__btn--confirm"
            onClick={() => void handleConfirm()}
            disabled={saving || !resolution.trim()}
          >
            Mark Done
          </button>
        </div>
      </div>
    </div>
  );
}
