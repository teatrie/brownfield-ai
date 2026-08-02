/**
 * Inline editor for epic pull request references.
 *
 * Displays current PR references as text with edit/clear controls.
 * Toggling into edit mode reveals an input field for setting new
 * PR references in "owner/repo#number" format.
 */

import { useState } from 'react';
import { useToast } from '../hooks/useToast';
import { clearEpicPrs, setEpicPrs } from '../api/client';

/** Props for the PrRefEditor component. */
interface PrRefEditorProps {
  /** The epic identifier to update PR references for. */
  epicId: string;
  /** Current PR reference string, or null if none set. */
  currentPrs: string | null;
  /** Callback invoked after a successful PR reference update. */
  onUpdate: (newPrs: string | null) => void;
}

/**
 * Inline PR reference editor with save and clear actions.
 *
 * Shows the current PR references as plain text, or a "No PRs"
 * placeholder when empty. An "Edit" button toggles an input field
 * with format hint. "Save" persists the new value, "Clear" removes
 * all PR references, and "Cancel" discards edits.
 *
 * @param props - Component props with epic ID, current PRs, and update handler.
 * @returns A styled editor element for PR references.
 */
export function PrRefEditor({
  epicId,
  currentPrs,
  onUpdate,
}: PrRefEditorProps): React.JSX.Element {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentPrs ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast, showToast } = useToast();

  /**
   * Persist the draft PR reference value via the API.
   */
  async function handleSave(): Promise<void> {
    const trimmed = draft.trim();
    if (!trimmed) return;
    setSaving(true);
    setError(null);
    try {
      await setEpicPrs(epicId, trimmed);
      showToast('PR references updated');
      onUpdate(trimmed);
      setEditing(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to update PRs';
      setError(message);
    } finally {
      setSaving(false);
    }
  }

  /**
   * Clear all PR references for the epic via the API.
   */
  async function handleClear(): Promise<void> {
    setSaving(true);
    setError(null);
    try {
      await clearEpicPrs(epicId);
      showToast('PR references cleared');
      onUpdate(null);
      setDraft('');
      setEditing(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to clear PRs';
      setError(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {editing ? (
        <div className="pr-ref-editor">
          <input
            type="text"
            className="pr-ref-editor__input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="owner/repo#123"
            disabled={saving}
            aria-label="PR reference"
          />
          <div className="pr-ref-editor__actions">
            <button
              type="button"
              className="pr-ref-editor__btn pr-ref-editor__btn--save"
              onClick={() => void handleSave()}
              disabled={saving || !draft.trim()}
            >
              Save
            </button>
            <button
              type="button"
              className="pr-ref-editor__btn"
              onClick={() => void handleClear()}
              disabled={saving}
            >
              Clear
            </button>
            <button
              type="button"
              className="pr-ref-editor__btn"
              onClick={() => {
                setDraft(currentPrs ?? '');
                setEditing(false);
                setError(null);
              }}
              disabled={saving}
            >
              Cancel
            </button>
          </div>
          {error && <span className="pr-ref-editor__error">{error}</span>}
        </div>
      ) : (
        <div className="pr-ref-editor">
          <span className="pr-ref-editor__display">
            {currentPrs ?? 'No PRs'}
          </span>
          <div className="pr-ref-editor__actions">
            <button
              type="button"
              className="pr-ref-editor__btn"
              onClick={() => {
                setDraft(currentPrs ?? '');
                setEditing(true);
              }}
            >
              Edit
            </button>
          </div>
        </div>
      )}
      {toast && <span className="toast">{toast}</span>}
    </>
  );
}
