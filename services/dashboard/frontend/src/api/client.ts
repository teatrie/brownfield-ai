/**
 * Typed API client for the Ledger Dashboard backend.
 *
 * Provides fetch wrappers that return strongly-typed responses
 * for epic listing, detail, and transition endpoints.
 */

import type {
  Artifact,
  ArtifactTimelineResponse,
  EpicDetailResponse,
  EpicListResponse,
  HomeStats,
  KbCollectionsResponse,
  KbDocument,
  KbDocumentListResponse,
  KbSearchResponse,
  TodoItem,
  TodoListResponse,
} from '../types';

/** Base path for all API requests (proxied by Vite in dev). */
const API_BASE = '/api';

/**
 * Generic JSON fetch wrapper with error handling.
 *
 * @typeParam T - Expected response body type.
 * @param path - URL path relative to the API base.
 * @returns Parsed JSON response body.
 * @throws Error when the response status is not ok.
 */
async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

/** Optional query parameters for the epic list endpoint. */
export interface FetchEpicsParams {
  /** Filter by epic status. */
  status?: string;
  /** Maximum number of results to return. */
  limit?: number;
  /** Offset for pagination. */
  offset?: number;
}

/**
 * Fetch a paginated list of epics from the registry.
 *
 * @param params - Optional filters for status, limit, and offset.
 * @returns Paginated epic list with a has_more flag.
 */
export async function fetchEpics(params?: FetchEpicsParams): Promise<EpicListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) {
    searchParams.set('status', params.status);
  }
  if (params?.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }
  if (params?.offset !== undefined) {
    searchParams.set('offset', String(params.offset));
  }
  const query = searchParams.toString();
  const path = query ? `/epics?${query}` : '/epics';
  return fetchJson<EpicListResponse>(path);
}

/**
 * Fetch full detail for a single epic including artifacts and resume context.
 *
 * @param epicId - The epic identifier (e.g. "DASH-0001").
 * @returns Epic record, artifacts, resume context, and valid transitions.
 */
export async function fetchEpicDetail(epicId: string): Promise<EpicDetailResponse> {
  return fetchJson<EpicDetailResponse>(`/epics/${encodeURIComponent(epicId)}`);
}

/** Response shape for the transitions endpoint. */
interface TransitionsResponse {
  /** Current epic status. */
  current_status: string;
  /** Status values the epic may transition to. */
  valid_transitions: string[];
}

/**
 * Fetch the valid status transitions for an epic.
 *
 * @param epicId - The epic identifier.
 * @returns Array of status strings the epic can transition to.
 */
export async function fetchEpicTransitions(epicId: string): Promise<string[]> {
  const data = await fetchJson<TransitionsResponse>(
    `/epics/${encodeURIComponent(epicId)}/transitions`,
  );
  return data.valid_transitions;
}

/** Parameters for filtering the artifact timeline. */
export interface FetchTimelineParams {
  /** Filter by artifact type. */
  artifact_type?: string;
  /** Filter by wave metadata field. */
  wave?: string;
  /** Filter by domain metadata field. */
  domain?: string;
  /** Filter by verdict (e.g. "GREEN", "FAIL", "RETRY"). */
  verdict?: string;
  /** Maximum number of results to return. */
  limit?: number;
  /** Offset for pagination. */
  offset?: number;
}

/**
 * Fetch artifacts for an epic's timeline with optional filters.
 *
 * @param epicId - The epic identifier.
 * @param params - Optional filter and pagination parameters.
 * @returns Paginated artifact timeline with a has_more flag.
 */
export async function fetchArtifactTimeline(
  epicId: string,
  params?: FetchTimelineParams,
): Promise<ArtifactTimelineResponse> {
  const searchParams = new URLSearchParams();
  if (params?.artifact_type) {
    searchParams.set('artifact_type', params.artifact_type);
  }
  if (params?.wave) {
    searchParams.set('wave', params.wave);
  }
  if (params?.domain) {
    searchParams.set('domain', params.domain);
  }
  if (params?.verdict) {
    searchParams.set('verdict', params.verdict);
  }
  if (params?.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }
  if (params?.offset !== undefined) {
    searchParams.set('offset', String(params.offset));
  }
  const query = searchParams.toString();
  const path = query
    ? `/artifacts/timeline/${encodeURIComponent(epicId)}?${query}`
    : `/artifacts/timeline/${encodeURIComponent(epicId)}`;
  return fetchJson<ArtifactTimelineResponse>(path);
}

/**
 * Fetch a single artifact by document ID.
 *
 * @param docId - The artifact document identifier.
 * @returns The full artifact record.
 */
export async function fetchArtifactDetail(docId: string): Promise<Artifact> {
  return fetchJson<Artifact>(`/artifacts/${encodeURIComponent(docId)}`);
}

/** A single search result from the unified search API. */
export interface SearchResultItem {
  /** Source collection: artifact, todo, or epic. */
  source: 'artifact' | 'todo' | 'epic';
  /** Unique identifier within the source collection. */
  id: string;
  /** Full document text content. */
  document: string;
  /** Metadata fields from the source collection. */
  metadata: Record<string, unknown>;
  /** Vector distance from the query (lower is more relevant). */
  distance: number;
}

/** Response shape for the search API. */
export interface SearchResponse {
  /** Ranked list of search results. */
  results: SearchResultItem[];
  /** The original query string. */
  query: string;
  /** The scope that was searched. */
  scope: string;
}

/**
 * Search across artifacts, TODOs, and epics via semantic similarity.
 *
 * @param q - The search query text.
 * @param scope - Scope to search: "all", "artifacts", "todos", or "epics".
 * @param limit - Maximum results per collection (default 20).
 * @returns Merged and ranked search results.
 */
export async function searchAll(
  q: string,
  scope: string = 'all',
  limit: number = 20,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, scope, limit: String(limit) });
  return fetchJson<SearchResponse>(`/search?${params}`);
}

/** Optional query parameters for the TODO list endpoint. */
export interface FetchTodosParams {
  /** Filter by status (default: "open"). */
  status?: string;
  /** Filter by category. */
  category?: string;
  /** Filter by linked epic ID. */
  epic_id?: string;
  /** Sort column: "priority", "created_at", "last_updated_at". */
  sort?: string;
  /** Sort direction: "asc" or "desc". */
  order?: string;
  /** Maximum number of results to return. */
  limit?: number;
  /** Offset for pagination. */
  offset?: number;
}

/**
 * Fetch a paginated list of TODOs with optional filters.
 *
 * @param params - Optional filters for status, category, epic, sort, and pagination.
 * @returns Paginated TODO list with total count and has_more flag.
 */
export async function fetchTodos(params?: FetchTodosParams): Promise<TodoListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) {
    searchParams.set('status', params.status);
  }
  if (params?.category) {
    searchParams.set('category', params.category);
  }
  if (params?.epic_id) {
    searchParams.set('epic_id', params.epic_id);
  }
  if (params?.sort) {
    searchParams.set('sort', params.sort);
  }
  if (params?.order) {
    searchParams.set('order', params.order);
  }
  if (params?.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }
  if (params?.offset !== undefined) {
    searchParams.set('offset', String(params.offset));
  }
  const query = searchParams.toString();
  const path = query ? `/todos?${query}` : '/todos';
  return fetchJson<TodoListResponse>(path);
}

/**
 * Fetch a single TODO item by its integer ID.
 *
 * @param todoId - The TODO row ID.
 * @returns The full TODO record.
 */
export async function fetchTodoById(todoId: number): Promise<TodoItem> {
  return fetchJson<TodoItem>(`/todos/${todoId}`);
}

/* ============================================================
   Write-action mutation helpers
   ============================================================ */

/**
 * Generic JSON mutation wrapper with error handling.
 *
 * Sends a non-GET request to the API and returns the parsed JSON
 * response. Extracts error detail from the response body on failure.
 *
 * @typeParam T - Expected response body type.
 * @param path - URL path relative to the API base.
 * @param method - HTTP method (PATCH, PUT, DELETE).
 * @param body - Optional request body to send as JSON.
 * @returns Parsed JSON response body.
 * @throws Error with detail message from the API response.
 */
async function mutateJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorBody.detail || `API error: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** Response shape for mutation endpoints. */
export interface MutationResponse {
  /** Whether the mutation succeeded. */
  success: boolean;
  /** Additional response fields returned by the API. */
  [key: string]: unknown;
}

/**
 * Update an epic's lifecycle status.
 *
 * @param epicId - The epic identifier.
 * @param newStatus - The target status value.
 * @returns Mutation result indicating success.
 */
export async function updateEpicStatus(
  epicId: string,
  newStatus: string,
): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/epics/${encodeURIComponent(epicId)}/status`,
    'PATCH',
    { new_status: newStatus },
  );
}

/**
 * Update an epic's priority value.
 *
 * @param epicId - The epic identifier.
 * @param priority - New priority value (0-9).
 * @returns Mutation result indicating success.
 */
export async function updateEpicPriority(
  epicId: string,
  priority: number,
): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/epics/${encodeURIComponent(epicId)}/priority`,
    'PATCH',
    { priority },
  );
}

/**
 * Set PR references for an epic.
 *
 * @param epicId - The epic identifier.
 * @param prRefs - PR reference string in "owner/repo#number" format.
 * @returns Mutation result indicating success.
 */
export async function setEpicPrs(
  epicId: string,
  prRefs: string,
): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/epics/${encodeURIComponent(epicId)}/prs`,
    'PUT',
    { pr_refs: prRefs },
  );
}

/**
 * Clear all PR references for an epic.
 *
 * @param epicId - The epic identifier.
 * @returns Mutation result indicating success.
 */
export async function clearEpicPrs(epicId: string): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/epics/${encodeURIComponent(epicId)}/prs`,
    'DELETE',
  );
}

/**
 * Mark a TODO item as done with a resolution note.
 *
 * @param todoId - The TODO item row ID.
 * @param resolution - Required resolution note text.
 * @returns Mutation result indicating success.
 */
export async function markTodoDone(
  todoId: number,
  resolution: string,
): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/todos/${todoId}/done`,
    'PATCH',
    { resolution },
  );
}

/**
 * Assign a TODO item to an epic.
 *
 * @param todoId - The TODO item row ID.
 * @param epicId - The epic identifier to assign to.
 * @returns Mutation result indicating success.
 */
export async function assignTodo(
  todoId: number,
  epicId: string,
): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/todos/${todoId}/assign`,
    'PATCH',
    { epic_id: epicId },
  );
}

/**
 * Update a TODO item's priority value.
 *
 * @param todoId - The TODO item row ID.
 * @param priority - New priority value (0-9).
 * @returns Mutation result indicating success.
 */
export async function updateTodoPriority(
  todoId: number,
  priority: number,
): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/todos/${todoId}/priority`,
    'PATCH',
    { priority },
  );
}

/**
 * Update a TODO item's category tag.
 *
 * @param todoId - The TODO item row ID.
 * @param category - New category string.
 * @returns Mutation result indicating success.
 */
export async function updateTodoCategory(
  todoId: number,
  category: string,
): Promise<MutationResponse> {
  return mutateJson<MutationResponse>(
    `/todos/${todoId}/category`,
    'PATCH',
    { category },
  );
}

/* ============================================================
   Knowledge Base read helpers
   ============================================================ */

/**
 * Fetch available KB collections with document counts.
 *
 * @returns Collection names and their document counts.
 */
export async function fetchKbCollections(): Promise<KbCollectionsResponse> {
  return fetchJson<KbCollectionsResponse>('/kb/collections');
}

/** Optional query parameters for the KB document list endpoint. */
export interface FetchKbDocumentsParams {
  /** Collection name to browse. */
  collection?: string;
  /** Maximum number of results to return. */
  limit?: number;
  /** Offset for pagination. */
  offset?: number;
}

/**
 * Fetch a paginated list of documents from a KB collection.
 *
 * @param params - Optional collection, limit, and offset parameters.
 * @returns Paginated document list with total count and has_more flag.
 */
export async function fetchKbDocuments(
  params?: FetchKbDocumentsParams,
): Promise<KbDocumentListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.collection) {
    searchParams.set('collection', params.collection);
  }
  if (params?.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }
  if (params?.offset !== undefined) {
    searchParams.set('offset', String(params.offset));
  }
  const query = searchParams.toString();
  const path = query ? `/kb/documents?${query}` : '/kb/documents';
  return fetchJson<KbDocumentListResponse>(path);
}

/**
 * Fetch a single KB document by ID.
 *
 * @param docId - The document identifier.
 * @param collection - Optional collection name (defaults to "long_term_document").
 * @returns The full document record with metadata.
 */
export async function fetchKbDocument(
  docId: string,
  collection?: string,
): Promise<KbDocument> {
  const searchParams = new URLSearchParams();
  if (collection) {
    searchParams.set('collection', collection);
  }
  const query = searchParams.toString();
  const path = query
    ? `/kb/documents/${encodeURIComponent(docId)}?${query}`
    : `/kb/documents/${encodeURIComponent(docId)}`;
  return fetchJson<KbDocument>(path);
}

/**
 * Semantic search within a KB collection.
 *
 * @param q - The search query text.
 * @param collection - Collection to search (defaults to "long_term_document").
 * @param limit - Maximum number of results (default 10).
 * @returns Ranked search results with distances.
 */
export async function searchKb(
  q: string,
  collection?: string,
  limit: number = 10,
): Promise<KbSearchResponse> {
  const searchParams = new URLSearchParams({ q, limit: String(limit) });
  if (collection) {
    searchParams.set('collection', collection);
  }
  return fetchJson<KbSearchResponse>(`/kb/search?${searchParams}`);
}

/* ============================================================
   Home stats
   ============================================================ */

/**
 * Fetch aggregated statistics for the dashboard home page.
 *
 * @returns Home stats including epics, todos, and optional activity data.
 */
export async function fetchHomeStats(): Promise<HomeStats> {
  return fetchJson<HomeStats>('/stats/home');
}
