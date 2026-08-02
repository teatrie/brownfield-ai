/**
 * Tooltip descriptions for dashboard UI elements.
 *
 * Centralizes all info-tip text so components stay clean
 * and descriptions remain consistent across views.
 */

import type { ArtifactType } from '../types';

/** Tooltip descriptions for each artifact type. */
export const ARTIFACT_TYPE_TIPS: Record<ArtifactType, string> = {
  plan_snapshot: 'Execution plan version captured at a point in time.',
  design_decision: 'Architectural or implementation decision with rationale.',
  gate_verdict: 'Review gate pass/fail result from dual-model or CI verification.',
  step_result: 'Outcome of a single implementation step within a wave.',
  wave_summary: 'Summary of a completed implementation wave.',
  session_exit: 'End-of-session exit assessment with verdict and next steps.',
  requirement_map: 'Mapping of requirements to implementation artifacts.',
  pr_created: 'Pull request creation record.',
  pr_merged: 'Pull request merge record.',
  todo_linked: 'TODO item linked to this epic.',
  ci_resolution: 'CI pipeline issue resolution record.',
  pr_changes_required: 'PR review feedback requiring changes before merge.',
};

/** Tooltip descriptions for epic detail sidebar sections. */
export const SECTION_TIPS = {
  linked_todos: 'Open TODO items associated with this epic. Managed via the /todo skill.',
  pull_requests: 'PR references linked to this epic. Updated automatically by /auto-pr or manually via the editor.',
  state_machine: 'Epic lifecycle status and valid transitions. States: backlog \u2192 pending \u2192 approved \u2192 in_progress \u2192 in_review \u2192 completed. Also: blocked, abandoned. See execution-ledger SKILL.md \u00A7 State Machine for full transition rules.',
} as const;
