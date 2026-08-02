import {
  fetchEpics,
  fetchTodos,
  fetchArtifactTimeline,
  fetchEpicDetail,
  fetchArtifactDetail,
  fetchEpicTransitions,
  fetchTodoById,
  searchAll,
  updateEpicStatus,
  updateEpicPriority,
  markTodoDone,
  setEpicPrs,
  clearEpicPrs,
  assignTodo,
  updateTodoPriority,
  updateTodoCategory,
} from '../../api/client';

/**
 * Helper to create a successful fetch Response mock.
 *
 * @param data - The JSON body to return.
 * @returns A mock Response-like object with ok: true.
 */
function okResponse(data: unknown): Partial<Response> {
  return {
    ok: true,
    json: async () => data,
  };
}

/**
 * Helper to create a failed fetch Response mock with a JSON body.
 *
 * @param status - HTTP status code.
 * @param statusText - HTTP status text.
 * @param body - Optional JSON body with detail field.
 * @returns A mock Response-like object with ok: false.
 */
function errorResponse(
  status: number,
  statusText: string,
  body?: Record<string, unknown>,
): Partial<Response> {
  return {
    ok: false,
    status,
    statusText,
    json: body
      ? async () => body
      : async () => {
          throw new Error('not json');
        },
  };
}

describe('API client', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // ----------------------------------------------------------------
  // Query param construction
  // ----------------------------------------------------------------
  describe('query param construction', () => {
    it('fetchEpics builds correct query string from {status, limit, offset}', async () => {
      fetchSpy.mockResolvedValue(okResponse({ epics: [], has_more: false }));
      await fetchEpics({ status: 'active', limit: 10, offset: 5 });

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toContain('/api/epics?');
      expect(url).toContain('status=active');
      expect(url).toContain('limit=10');
      expect(url).toContain('offset=5');
    });

    it('fetchEpics omits empty params (no status=undefined)', async () => {
      fetchSpy.mockResolvedValue(okResponse({ epics: [], has_more: false }));
      await fetchEpics({ limit: 10 });

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).not.toContain('status=');
      expect(url).not.toContain('offset=');
      expect(url).toContain('limit=10');
    });

    it('fetchEpics with undefined params produces path /epics with no ?', async () => {
      fetchSpy.mockResolvedValue(okResponse({ epics: [], has_more: false }));
      await fetchEpics();

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toBe('/api/epics');
      expect(url).not.toContain('?');
    });

    it('fetchTodos builds query from {status, category, epic_id, sort, order, limit, offset}', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({ todos: [], total: 0, has_more: false }),
      );
      await fetchTodos({
        status: 'open',
        category: 'bug',
        epic_id: 'E-1',
        sort: 'priority',
        order: 'asc',
        limit: 25,
        offset: 10,
      });

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toContain('status=open');
      expect(url).toContain('category=bug');
      expect(url).toContain('epic_id=E-1');
      expect(url).toContain('sort=priority');
      expect(url).toContain('order=asc');
      expect(url).toContain('limit=25');
      expect(url).toContain('offset=10');
    });

    it('fetchTodos with {offset: 0} emits offset=0 (boundary: 0 is falsy but code uses !== undefined)', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({ todos: [], total: 0, has_more: false }),
      );
      await fetchTodos({ offset: 0 });

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toContain('offset=0');
    });

    it('fetchArtifactTimeline builds query from {artifact_type, wave, domain, verdict, limit, offset}', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({ artifacts: [], has_more: false }),
      );
      await fetchArtifactTimeline('EPIC-1', {
        artifact_type: 'step_result',
        wave: '1',
        domain: 'backend',
        verdict: 'GREEN',
        limit: 50,
        offset: 20,
      });

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toContain('artifact_type=step_result');
      expect(url).toContain('wave=1');
      expect(url).toContain('domain=backend');
      expect(url).toContain('verdict=GREEN');
      expect(url).toContain('limit=50');
      expect(url).toContain('offset=20');
    });

    it('fetchArtifactTimeline with all-empty-string filters produces no query string', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({ artifacts: [], has_more: false }),
      );
      await fetchArtifactTimeline('EPIC-1', {
        artifact_type: '',
        wave: '',
        domain: '',
        verdict: '',
      });

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toBe('/api/artifacts/timeline/EPIC-1');
      expect(url).not.toContain('?');
    });

    it('searchAll uses default scope and limit when not provided', async () => {
      fetchSpy.mockResolvedValue(okResponse({ results: [], query: 'test', scope: 'all' }));
      await searchAll('test query');

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toContain('scope=all');
      expect(url).toContain('limit=20');
    });

    it('searchAll encodes query, scope, and limit params', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({ results: [], query: 'test', scope: 'all' }),
      );
      await searchAll('hello world', 'artifacts', 10);

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toContain('/api/search?');
      expect(url).toContain('q=hello+world');
      expect(url).toContain('scope=artifacts');
      expect(url).toContain('limit=10');
    });
  });

  // ----------------------------------------------------------------
  // URL encoding
  // ----------------------------------------------------------------
  describe('URL encoding', () => {
    it('fetchEpicDetail encodes special characters in epic ID', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({
          epic: {},
          artifacts: [],
          context: {},
          valid_transitions: [],
        }),
      );
      await fetchEpicDetail('EPIC/001&test');

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toBe('/api/epics/EPIC%2F001%26test');
    });

    it('fetchArtifactDetail encodes special characters in doc ID', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({ id: 'test', document: '', metadata: {} }),
      );
      await fetchArtifactDetail('doc/special&chars');

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toBe('/api/artifacts/doc%2Fspecial%26chars');
    });

    it('fetchEpicTransitions returns valid_transitions array', async () => {
      fetchSpy.mockResolvedValue(
        okResponse({
          current_status: 'in_progress',
          valid_transitions: ['completed', 'abandoned'],
        }),
      );

      const result = await fetchEpicTransitions('EPIC-1');
      expect(result).toEqual(['completed', 'abandoned']);
    });

    it('fetchTodoById fetches single TODO by integer ID', async () => {
      const todo = { id: 42, title: 'Fix bug', status: 'open', priority: 1 };
      fetchSpy.mockResolvedValue(okResponse(todo));

      const result = await fetchTodoById(42);

      const url = fetchSpy.mock.calls[0]![0] as string;
      expect(url).toBe('/api/todos/42');
      expect(result).toEqual(todo);
    });
  });

  // ----------------------------------------------------------------
  // Error handling
  // ----------------------------------------------------------------
  describe('error handling', () => {
    it('fetchJson throws with status text on non-ok response', async () => {
      fetchSpy.mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      await expect(fetchEpics()).rejects.toThrow(
        'API error: 500 Internal Server Error',
      );
    });

    it('fetchJson rejects when fetch itself rejects (network failure)', async () => {
      fetchSpy.mockRejectedValue(new TypeError('Failed to fetch'));

      await expect(fetchEpics()).rejects.toThrow('Failed to fetch');
    });

    it('mutateJson extracts detail field from error response body', async () => {
      fetchSpy.mockResolvedValue(
        errorResponse(422, 'Unprocessable Entity', {
          detail: 'Invalid status transition',
        }),
      );

      await expect(
        updateEpicStatus('EPIC-1', 'invalid'),
      ).rejects.toThrow('Invalid status transition');
    });

    it('mutateJson falls back to status text when error body is not JSON', async () => {
      fetchSpy.mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        json: async () => {
          throw new Error('not json');
        },
      });

      await expect(
        updateEpicStatus('EPIC-1', 'active'),
      ).rejects.toThrow('Server Error');
    });
  });

  // ----------------------------------------------------------------
  // Mutation helpers
  // ----------------------------------------------------------------
  describe('mutation helpers', () => {
    beforeEach(() => {
      fetchSpy.mockResolvedValue(okResponse({ success: true }));
    });

    it('updateEpicStatus sends PATCH with {new_status} body', async () => {
      await updateEpicStatus('EPIC-1', 'completed');

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/epics/EPIC-1/status');
      expect(options.method).toBe('PATCH');
      expect(JSON.parse(options.body as string)).toEqual({
        new_status: 'completed',
      });
      expect(
        (options.headers as Record<string, string>)['Content-Type'],
      ).toBe('application/json');
    });

    it('updateEpicPriority sends PATCH with {priority} body', async () => {
      await updateEpicPriority('EPIC-1', 3);

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/epics/EPIC-1/priority');
      expect(options.method).toBe('PATCH');
      expect(JSON.parse(options.body as string)).toEqual({ priority: 3 });
    });

    it('markTodoDone sends PATCH with {resolution} body', async () => {
      await markTodoDone(42, 'Fixed in PR #123');

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/todos/42/done');
      expect(options.method).toBe('PATCH');
      expect(JSON.parse(options.body as string)).toEqual({
        resolution: 'Fixed in PR #123',
      });
    });

    it('setEpicPrs sends PUT with {pr_refs} body', async () => {
      await setEpicPrs('EPIC-1', 'org/repo#42');

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/epics/EPIC-1/prs');
      expect(options.method).toBe('PUT');
      expect(JSON.parse(options.body as string)).toEqual({
        pr_refs: 'org/repo#42',
      });
    });

    it('clearEpicPrs sends DELETE with no body AND no Content-Type header', async () => {
      await clearEpicPrs('EPIC-1');

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/epics/EPIC-1/prs');
      expect(options.method).toBe('DELETE');
      expect(options.body).toBeUndefined();
      expect(options.headers).toEqual({});
    });

    it('assignTodo sends PATCH with {epic_id} body', async () => {
      await assignTodo(42, 'EPIC-1');

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/todos/42/assign');
      expect(options.method).toBe('PATCH');
      expect(JSON.parse(options.body as string)).toEqual({
        epic_id: 'EPIC-1',
      });
    });

    it('updateTodoPriority sends PATCH with {priority} body', async () => {
      await updateTodoPriority(42, 5);

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/todos/42/priority');
      expect(options.method).toBe('PATCH');
      expect(JSON.parse(options.body as string)).toEqual({ priority: 5 });
    });

    it('updateTodoCategory sends PATCH with {category} body', async () => {
      await updateTodoCategory(42, 'bug');

      const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('/api/todos/42/category');
      expect(options.method).toBe('PATCH');
      expect(JSON.parse(options.body as string)).toEqual({ category: 'bug' });
    });
  });
});
