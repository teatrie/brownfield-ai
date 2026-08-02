/**
 * Shared TypeScript type definitions for the Ledger Dashboard.
 *
 * Provides interfaces and enums consumed by the API client,
 * React components, and page modules.
 */

/** Valid statuses for an epic lifecycle. */
export type EpicStatus =
  | 'backlog'
  | 'pending'
  | 'approved'
  | 'in_progress'
  | 'in_review'
  | 'completed'
  | 'abandoned'
  | 'blocked';

/** Epic metadata from the SQLite registry. */
export interface Epic {
  /** Unique identifier for the epic (e.g. "DASH-0001"). */
  epic_id: string;
  /** Current lifecycle status. */
  status: EpicStatus;
  /** Numeric priority (lower is higher priority). */
  priority: number;
  /** Comma-separated list of epic IDs this epic depends on. */
  depends_on: string;
  /** Agent or user that claimed the epic. */
  claimed_by: string;
  /** ISO-8601 timestamp when the epic was claimed. */
  claimed_at: string;
  /** Human-readable epic title. */
  title: string;
  /** ISO-8601 creation timestamp. */
  created_at: string;
  /** ISO-8601 last update timestamp. */
  last_updated_at: string;
  /** PR references in "owner/repo#number" format, or null. */
  current_prs: string | null;
}

/** Recognized artifact types stored in the execution ledger. */
export type ArtifactType =
  | 'plan_snapshot'
  | 'design_decision'
  | 'gate_verdict'
  | 'step_result'
  | 'wave_summary'
  | 'requirement_map'
  | 'pr_created'
  | 'pr_merged'
  | 'todo_linked'
  | 'ci_resolution'
  | 'pr_changes_required'
  | 'session_exit';

/** Metadata attached to each execution ledger artifact. */
export interface ArtifactMetadata {
  /** Epic this artifact belongs to. */
  epic_id: string;
  /** Category of artifact. */
  artifact_type: ArtifactType;
  /** Model identifier that produced the artifact. */
  agent_model: string;
  /** Implementation wave (e.g. "0", "1"). */
  wave: string;
  /** Step within the wave. */
  step: string;
  /** Domain scope (e.g. "backend", "frontend"). */
  domain: string;
  /** Gate verdict value (e.g. "GREEN", "FAIL"). */
  verdict: string;
  /** ISO-8601 timestamp of artifact creation. */
  timestamp: string;
  /** Artifact lifecycle status. */
  artifact_status: string;
  /** Schema version of the artifact. */
  version: number;
  /** Attempt counter for retried operations. */
  attempt: string;
  /** Sub-plan reference if applicable. */
  sub_plan: string;
  /** Parent artifact ID for hierarchical relationships. */
  parent_id: string;
  /** Git branches associated with the artifact. */
  branches: string;
  /** Epic status at the time of artifact creation. */
  epic_status: string;
  /** Role of the agent that produced the artifact. */
  agent_role: string;
}

/** Artifact from the ChromaDB execution_ledger collection. */
export interface Artifact {
  /** Unique artifact identifier. */
  id: string;
  /** Full text content of the artifact. */
  document: string;
  /** Structured metadata fields. */
  metadata: ArtifactMetadata;
}

/** TODO item from the SQLite todos table. */
export interface TodoItem {
  /** Auto-incremented row ID. */
  id: number;
  /** Short description of the task. */
  title: string;
  /** Current status (e.g. "open", "done", "assigned"). */
  status: string;
  /** Numeric priority (lower is higher priority). */
  priority: number;
  /** Optional grouping category. */
  category?: string;
  /** Optional linked epic identifier. */
  epic_id?: string;
  /** Longer description of the task. */
  description?: string;
  /** ISO-8601 creation timestamp. */
  created_at?: string;
  /** ISO-8601 last update timestamp. */
  last_updated_at?: string;
}

/** API response for GET /api/todos. */
export interface TodoListResponse {
  /** Array of TODO item records. */
  todos: TodoItem[];
  /** Total number of matching records. */
  total: number;
  /** Whether additional pages of results exist. */
  has_more: boolean;
}

/** Resume context returned by the epic detail endpoint. */
export interface ResumeContext {
  /** Latest plan snapshot artifact, or null if none exists. */
  plan_snapshot: Artifact | null;
  /** All design decision artifacts for the epic. */
  design_decisions: Artifact[];
  /** All step result artifacts for the epic. */
  step_results: Artifact[];
  /** All wave summary artifacts for the epic. */
  wave_summaries: Artifact[];
  /** All gate verdict artifacts for the epic. */
  gate_verdicts: Artifact[];
  /** Latest requirement map artifact, or null if none exists. */
  requirement_map: Artifact | null;
  /** All PR-created artifacts for the epic. */
  pr_created: Artifact[];
  /** All PR-merged artifacts for the epic. */
  pr_merged: Artifact[];
  /** Open TODO items linked to the epic. */
  open_todos: TodoItem[];
}

/** API response for GET /api/epics. */
export interface EpicListResponse {
  /** Array of epic records. */
  epics: Epic[];
  /** Whether additional pages of results exist. */
  has_more: boolean;
}

/** API response for GET /api/epics/:id. */
export interface EpicDetailResponse {
  /** The requested epic record. */
  epic: Epic;
  /** All artifacts associated with the epic. */
  artifacts: Artifact[];
  /** Structured resume context for the epic. */
  context: ResumeContext;
  /** Status values the epic may transition to from its current state. */
  valid_transitions: string[];
}

/** WebSocket event envelope for real-time updates. */
export interface WsEvent {
  /** Event type identifier. */
  type: string;
  /** Optional epic identifier for targeted events. */
  epic_id?: string;
  /** Event payload data. */
  data?: unknown;
}

/** WebSocket event emitted when an epic's metadata changes. */
export interface WsEpicChangeEvent extends WsEvent {
  /** Discriminant for epic change events. */
  type: 'epic_change';
  /** Epic that changed. */
  epic_id: string;
  /** Changed epic fields. */
  data: {
    /** New status value. */
    status: string;
    /** Updated timestamp. */
    last_updated_at: string;
  };
}

/** WebSocket event emitted when a new artifact is detected. */
export interface WsArtifactNewEvent extends WsEvent {
  /** Discriminant for new artifact events. */
  type: 'artifact_new';
  /** Epic the artifact belongs to. */
  epic_id: string;
  /** The new artifact data. */
  data: {
    /** Artifact identifier. */
    id: string;
    /** Artifact document content. */
    document: string;
    /** Artifact metadata fields. */
    metadata: ArtifactMetadata;
  };
}

/** API response for GET /api/artifacts/timeline/:epicId. */
export interface ArtifactTimelineResponse {
  /** Array of artifact records. */
  artifacts: Artifact[];
  /** Whether additional pages of results exist. */
  has_more: boolean;
}

/**
 * State machine transitions map.
 *
 * Keys are the source status; values are arrays of
 * permitted target statuses.
 */
export const VALID_TRANSITIONS: Record<string, string[]> = {
  backlog: ['pending', 'approved'],
  pending: ['approved'],
  approved: ['in_progress'],
  in_progress: ['completed', 'abandoned', 'approved', 'pending', 'in_review', 'blocked'],
  in_review: ['completed', 'backlog', 'abandoned', 'blocked'],
  blocked: ['approved', 'abandoned'],
};

/** KB collection summary from GET /api/kb/collections. */
export interface KbCollection {
  /** Collection name (e.g. "long_term_document", "chat_history"). */
  name: string;
  /** Number of documents in the collection. */
  count: number;
}

/** API response for GET /api/kb/collections. */
export interface KbCollectionsResponse {
  /** Array of collection summaries. */
  collections: KbCollection[];
}

/** Single document from a KB collection. */
export interface KbDocument {
  /** Unique document identifier (SHA-256 hash). */
  id: string;
  /** Full text content. */
  document: string;
  /** Arbitrary metadata key-value pairs. */
  metadata: Record<string, unknown>;
}

/** API response for GET /api/kb/documents. */
export interface KbDocumentListResponse {
  /** Array of document records. */
  documents: KbDocument[];
  /** Total number of documents in the collection. */
  total: number;
  /** Whether additional pages exist. */
  has_more: boolean;
}

/** Single search result from KB semantic search. */
export interface KbSearchResult {
  /** Document identifier. */
  id: string;
  /** Full text content. */
  document: string;
  /** Arbitrary metadata key-value pairs. */
  metadata: Record<string, unknown>;
  /** Vector distance from the query (lower is more relevant). */
  distance: number;
}

/** API response for GET /api/kb/search. */
export interface KbSearchResponse {
  /** Ranked list of search results. */
  results: KbSearchResult[];
  /** The original query string. */
  query: string;
  /** The collection that was searched. */
  collection: string;
}

/** Single category count entry for TODO breakdown. */
export interface CategoryCount {
  /** Category name (or "uncategorized" for null). */
  category: string;
  /** Number of TODOs in this category. */
  count: number;
}

/** Epic aggregate statistics from the stats endpoint. */
export interface EpicStats {
  /** Count of epics per lifecycle status. */
  by_status: Record<string, number>;
  /** Number of in_progress + in_review epics. */
  active: number;
  /** Number of blocked epics. */
  blocked: number;
  /** Epics completed in the last 24 hours. */
  completed_24h: number;
  /** Epics created in the last 24 hours. */
  created_24h: number;
  /** Total epic count across all statuses. */
  total: number;
}

/** TODO aggregate statistics from the stats endpoint. */
export interface TodoStats {
  /** Number of open TODOs. */
  open: number;
  /** Number of assigned TODOs. */
  assigned: number;
  /** Number of done TODOs. */
  done: number;
  /** Total TODO count across all statuses. */
  total: number;
  /** Number of open TODOs with priority <= 3. */
  high_priority_open: number;
  /** Open TODO counts broken down by category. */
  by_category: CategoryCount[];
}

/** Activity statistics from ChromaDB artifacts. */
export interface ActivityStats {
  /** Artifacts created in the last hour. */
  artifacts_1h: number;
  /** Artifacts created in the last 24 hours. */
  artifacts_24h: number;
  /** Gate verdict pass/fail counts in 24h. */
  gates_24h: { pass: number; fail: number };
  /** PRs created in the last 7 days. */
  prs_created_7d: number;
  /** PRs merged in the last 7 days. */
  prs_merged_7d: number;
}

/** Full home page stats response from GET /api/stats/home. */
export interface HomeStats {
  /** Epic aggregate statistics. */
  epics: EpicStats;
  /** TODO aggregate statistics. */
  todos: TodoStats;
  /** Activity statistics, or null if ChromaDB is unavailable. */
  activity: ActivityStats | null;
}
