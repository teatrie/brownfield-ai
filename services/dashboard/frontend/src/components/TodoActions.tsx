/**
 * Action buttons for TODO item management.
 *
 * Provides inline controls for marking a TODO as done,
 * editing priority, and assigning to an epic. Integrates
 * with PriorityEditor and DoneModal components.
 */

import { useState } from 'react';
import { useToast } from '../hooks/useToast';
import { assignTodo, updateTodoPriority } from '../api/client';
import { DoneModal } from './DoneModal';
import { PriorityEditor } from './PriorityEditor';

/** Props for the TodoActions component. */
interface TodoActionsProps {
  /** The TODO item ID to perform actions on. */
  todoId: number;
  /** Current status of the TODO item. */
  currentStatus: string;
  /** Current priority value (0-9). */
  currentPriority: number;
  /** Callback invoked after any successful mutation to refresh data. */
  onUpdate: () => void;
}

/**
 * Inline action controls for a TODO list item.
 *
 * Renders a set of action buttons depending on the TODO state:
 * - "Done" button (visible when status is not "done") opens a DoneModal
 * - PriorityEditor for inline priority changes
 * - "Assign" button with an inline epic ID input field
 *
 * @param props - Component props with todo metadata and update callback.
 * @returns A flex container with action controls.
 */
export function TodoActions({
  todoId,
  currentStatus,
  currentPriority,
  onUpdate,
}: TodoActionsProps): React.JSX.Element {
  const [showDoneModal, setShowDoneModal] = useState(false);
  const [showAssignInput, setShowAssignInput] = useState(false);
  const [assignEpicId, setAssignEpicId] = useState('');
  const [assigning, setAssigning] = useState(false);
  const { toast, showToast } = useToast();

  /**
   * Persist the epic assignment for this TODO via the API.
   */
  async function handleAssign(): Promise<void> {
    const trimmed = assignEpicId.trim();
    if (!trimmed) return;
    setAssigning(true);
    try {
      await assignTodo(todoId, trimmed);
      setShowAssignInput(false);
      setAssignEpicId('');
      onUpdate();
    } catch (err) {
      console.error(err);
      showToast('Assignment failed');
    } finally {
      setAssigning(false);
    }
  }

  /**
   * Handle Enter key in the assign input to submit.
   *
   * @param event - The keyboard event from the input.
   */
  function handleAssignKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter') {
      void handleAssign();
    } else if (event.key === 'Escape') {
      setShowAssignInput(false);
      setAssignEpicId('');
    }
  }

  return (
    <div className="todo-actions">
      {currentStatus.toLowerCase() !== 'done' && (
        <button
          type="button"
          className="todo-actions__btn todo-actions__btn--done"
          onClick={() => setShowDoneModal(true)}
        >
          Done
        </button>
      )}

      <PriorityEditor
        value={currentPriority}
        onSave={async (newPriority) => {
          try {
            await updateTodoPriority(todoId, newPriority);
            onUpdate();
          } catch (err) {
            console.error(err);
            showToast('Priority update failed');
          }
        }}
      />

      {showAssignInput ? (
        <input
          type="text"
          className="todo-actions__assign-input"
          value={assignEpicId}
          onChange={(e) => setAssignEpicId(e.target.value)}
          onKeyDown={handleAssignKeyDown}
          onBlur={() => {
            if (!assignEpicId.trim()) {
              setShowAssignInput(false);
            }
          }}
          placeholder="EPIC-ID"
          disabled={assigning}
          aria-label="Assign to epic"
          autoFocus
        />
      ) : (
        <button
          type="button"
          className="todo-actions__btn"
          onClick={() => setShowAssignInput(true)}
        >
          Assign
        </button>
      )}

      {showDoneModal && (
        <DoneModal
          todoId={todoId}
          onClose={() => setShowDoneModal(false)}
          onDone={onUpdate}
        />
      )}

      {toast && <span className="toast">{toast}</span>}
    </div>
  );
}
