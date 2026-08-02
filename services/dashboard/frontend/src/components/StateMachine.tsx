/**
 * Visual state machine component for epic lifecycle transitions.
 *
 * Renders all possible epic states as nodes in a grid layout,
 * highlighting the current state and showing allowed transitions
 * with directional arrows. Terminal states (completed, abandoned)
 * are visually distinct.
 */

import type { EpicStatus } from '../types';

/** Props for the StateMachine component. */
interface StateMachineProps {
  /** The epic's current lifecycle status. */
  currentStatus: EpicStatus;
  /** Map of source status to allowed target statuses. */
  transitions: Record<string, string[]>;
}

/** All possible epic statuses in lifecycle order. */
const ALL_STATES: EpicStatus[] = [
  'backlog',
  'pending',
  'approved',
  'in_progress',
  'in_review',
  'completed',
  'blocked',
  'abandoned',
];

/** Statuses that represent terminal/end states. */
const TERMINAL_STATES: ReadonlySet<string> = new Set(['completed', 'abandoned']);

/**
 * Format a status string for display in a state node.
 *
 * @param status - Raw status string (e.g. "in_progress").
 * @returns Formatted display string (e.g. "In Progress").
 */
function formatState(status: string): string {
  return status
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Visual state machine diagram for epic lifecycle.
 *
 * Displays all states as nodes in a responsive grid. The current
 * state is highlighted with the accent color and a bolder border.
 * States reachable from the current state show a directional
 * arrow indicator. Terminal states use dashed borders.
 *
 * @param props - Component props with current status and transition map.
 * @returns A styled div containing the state machine visualization.
 */
export function StateMachine({ currentStatus, transitions }: StateMachineProps): React.JSX.Element {
  const allowedTargets = transitions[currentStatus] ?? [];
  const targetSet = new Set(allowedTargets);

  return (
    <div className="state-machine">
      {ALL_STATES.map((state) => {
        const isCurrent = state === currentStatus;
        const isTarget = targetSet.has(state);
        const isTerminal = TERMINAL_STATES.has(state);

        let className = 'state-node';
        if (isCurrent) className += ' state-node--current';
        if (isTerminal) className += ' state-node--terminal';
        if (isTarget) className += ' state-node--target';

        return (
          <div key={state} className={className}>
            {isTarget && <span className="state-arrow">&larr;</span>}
            <span className="state-node__label">{formatState(state)}</span>
            {isCurrent && <span className="state-node__indicator">&#9679;</span>}
          </div>
        );
      })}
    </div>
  );
}
