/**
 * Inline priority editor with click-to-edit number stepper.
 *
 * Renders a priority pill that transforms into a number input
 * on click. Supports range 0-9, and persists via the provided
 * onSave callback on blur or Enter key.
 */

import { useEffect, useRef, useState } from 'react';

/** Props for the PriorityEditor component. */
interface PriorityEditorProps {
  /** Current priority value (0-9). */
  value: number;
  /** Async callback to persist the new priority value. */
  onSave: (newPriority: number) => Promise<void>;
}

/**
 * Inline editable priority pill with number input.
 *
 * Displays the current priority as a compact pill badge. Clicking
 * the pill reveals a small number input (0-9). The value is saved
 * on blur or when Enter is pressed. Escape cancels editing.
 *
 * @param props - Component props with current value and save handler.
 * @returns A styled inline editor element.
 */
export function PriorityEditor({ value, onSave }: PriorityEditorProps): React.JSX.Element {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value));
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  /**
   * Persist the draft value and exit edit mode.
   */
  async function commitValue(): Promise<void> {
    const parsed = Number(draft);
    if (isNaN(parsed) || parsed < 0 || parsed > 9) {
      setDraft(String(value));
      setEditing(false);
      return;
    }
    if (parsed === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(parsed);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  /**
   * Handle keyboard events for save (Enter) and cancel (Escape).
   *
   * @param event - The keyboard event from the input.
   */
  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter') {
      void commitValue();
    } else if (event.key === 'Escape') {
      setDraft(String(value));
      setEditing(false);
    }
  }

  if (editing) {
    return (
      <span className="priority-editor">
        <input
          ref={inputRef}
          type="number"
          min={0}
          max={9}
          className="priority-editor__input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commitValue()}
          onKeyDown={handleKeyDown}
          disabled={saving}
          aria-label="Edit priority"
        />
      </span>
    );
  }

  return (
    <span className="priority-editor">
      <button
        type="button"
        className="priority-editor__pill"
        onClick={() => {
          setDraft(String(value));
          setEditing(true);
        }}
        aria-label={`Priority ${value}, click to edit`}
      >
        P{value}
      </button>
    </span>
  );
}
