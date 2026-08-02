/**
 * TODO list item component for the epic detail sidebar.
 *
 * Renders a single TODO with a colored status dot, title,
 * optional category tag, priority badge, and optional action
 * controls for marking done, editing priority, and assigning.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { TodoItem as TodoItemType } from '../types';
import { TodoActions } from './TodoActions';

/** Props for the TodoItem component. */
interface TodoItemProps {
  /** The TODO item to display. */
  todo: TodoItemType;
  /** Optional callback invoked after a write action to refresh data. */
  onUpdate?: () => void;
}

/**
 * Determine the CSS modifier class for a TODO status value.
 *
 * @param status - TODO status string (e.g. "done", "open", "assigned").
 * @returns CSS class suffix for dot coloring.
 */
function getStatusDotClass(status: string): string {
  const lower = status.toLowerCase();
  if (lower === 'done' || lower === 'completed') return 'done';
  if (lower === 'open' || lower === 'pending') return 'open';
  return 'assigned';
}

/**
 * Single TODO list item with status indicator, title, metadata, and actions.
 *
 * Displays a colored dot (green for done, orange for open, gray
 * for assigned), the task title, an optional category tag, a
 * priority number badge, and inline action buttons when an
 * onUpdate callback is provided.
 *
 * @param props - Component props containing the TODO item and optional update handler.
 * @returns A styled div element.
 */
export function TodoItemRow({ todo, onUpdate }: TodoItemProps): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`todo-item${expanded ? ' todo-item--expanded' : ''}`}>
      <div className="todo-item__header">
        <div
          className="todo-item__toggle"
          role="button"
          tabIndex={0}
          aria-expanded={expanded}
          onClick={() => setExpanded((p) => !p)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              setExpanded((p) => !p);
            }
          }}
        >
          <span className={`todo-item__dot todo-item__dot--${getStatusDotClass(todo.status)}`} />
          <span className="todo-item__id">TODO-{String(todo.id).padStart(4, '0')}</span>
          <span className="todo-item__title">{todo.title}</span>
          {todo.category && (
            <span className="todo-item__category">{todo.category}</span>
          )}
          <span className="todo-item__priority">{todo.priority}</span>
        </div>
        {onUpdate && (
          <TodoActions
            todoId={todo.id}
            currentStatus={todo.status}
            currentPriority={todo.priority}
            onUpdate={onUpdate}
          />
        )}
      </div>
      {expanded && (
        <div className="todo-item__detail">
          {todo.description && (
            <p className="todo-item__description">{todo.description}</p>
          )}
          <div className="todo-item__meta">
            <span className="todo-item__meta-label">Status</span>
            <span>{todo.status}</span>
            {todo.epic_id && (
              <>
                <span className="todo-item__meta-label">Epic</span>
                <Link to={`/epics/${todo.epic_id}`} className="todo-item__epic-link mono">
                  {todo.epic_id}
                </Link>
              </>
            )}
            {todo.created_at && (
              <>
                <span className="todo-item__meta-label">Created</span>
                <span className="mono">{new Date(todo.created_at).toLocaleString()}</span>
              </>
            )}
            {todo.last_updated_at && (
              <>
                <span className="todo-item__meta-label">Updated</span>
                <span className="mono">{new Date(todo.last_updated_at).toLocaleString()}</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
