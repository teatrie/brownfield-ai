import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { KnowledgeBasePage } from '../../pages/KnowledgeBasePage';
import {
  fetchKbCollections,
  fetchKbDocuments,
  searchKb,
} from '../../api/client';

vi.mock('../../api/client', () => ({
  fetchKbCollections: vi.fn(),
  fetchKbDocuments: vi.fn(),
  searchKb: vi.fn(),
  // Re-export other functions as passthrough to prevent import errors
  fetchEpics: vi.fn(),
  fetchEpicDetail: vi.fn(),
  fetchEpicTransitions: vi.fn(),
  fetchArtifactTimeline: vi.fn(),
  fetchArtifactDetail: vi.fn(),
  searchAll: vi.fn(),
  fetchTodos: vi.fn(),
  fetchTodoById: vi.fn(),
  updateEpicStatus: vi.fn(),
  updateEpicPriority: vi.fn(),
  setEpicPrs: vi.fn(),
  clearEpicPrs: vi.fn(),
  markTodoDone: vi.fn(),
  assignTodo: vi.fn(),
  updateTodoPriority: vi.fn(),
  updateTodoCategory: vi.fn(),
  fetchKbDocument: vi.fn(),
}));

const mockFetchKbCollections = fetchKbCollections as ReturnType<typeof vi.fn>;
const mockFetchKbDocuments = fetchKbDocuments as ReturnType<typeof vi.fn>;
const mockSearchKb = searchKb as ReturnType<typeof vi.fn>;

function renderPage(): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={['/knowledge']}>
      <Routes>
        <Route path="/knowledge" element={<KnowledgeBasePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('KnowledgeBasePage', () => {
  beforeEach(() => {
    mockFetchKbCollections.mockResolvedValue({
      collections: [
        { name: 'long_term_document', count: 5 },
        { name: 'chat_history', count: 3 },
      ],
    });
    mockFetchKbDocuments.mockResolvedValue({
      documents: [
        { id: 'abc12345', document: 'First document content here', metadata: { source: 'manual' } },
        { id: 'def67890', document: 'Second document content', metadata: { topic: 'testing' } },
      ],
      total: 2,
      has_more: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders collection selector with options', async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByLabelText('Select collection')).toBeInTheDocument();
    });

    const select = screen.getByLabelText('Select collection');
    const options = within(select).getAllByRole('option');
    expect(options.length).toBe(3); // All + 2 collections
  });

  it('renders document list from mock API', async () => {
    renderPage();

    // Default "All" fetches from both collections; mock returns same data for each
    // Total = 2 + 2 = 4
    await waitFor(() => {
      expect(screen.getByText('4 document(s)')).toBeInTheDocument();
    });
  });

  it('switching collection triggers refetch', async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByLabelText('Select collection')).toBeInTheDocument();
    });

    mockFetchKbDocuments.mockResolvedValueOnce({
      documents: [],
      total: 0,
      has_more: false,
    });

    await user.selectOptions(screen.getByLabelText('Select collection'), 'chat_history');

    await waitFor(() => {
      expect(mockFetchKbDocuments).toHaveBeenCalledWith(
        expect.objectContaining({ collection: 'chat_history' }),
      );
    });
  });

  it('search input triggers search endpoint', async () => {
    const user = userEvent.setup();
    mockSearchKb.mockResolvedValue({
      results: [
        { id: 'res1', document: 'Search result', metadata: {}, distance: 0.15 },
      ],
      query: 'test query',
      collection: 'long_term_document',
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByLabelText('Search documents')).toBeInTheDocument();
    });

    const searchInput = screen.getByLabelText('Search documents');
    await user.type(searchInput, 'test query{Enter}');

    // "All" is default — searchKb called once per collection
    await waitFor(() => {
      expect(mockSearchKb).toHaveBeenCalledTimes(2);
    });

    await waitFor(() => {
      // Same mock for both collections produces duplicate res1 entries
      expect(screen.getAllByText(/res1/).length).toBeGreaterThanOrEqual(1);
    });
  });

  it('document row click expands detail panel', async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getAllByText(/abc12345/).length).toBeGreaterThanOrEqual(1);
    });

    // Click the first document row with that id
    const matches = screen.getAllByText(/abc12345/);
    const row = matches[0]?.closest('[role="button"]') as HTMLElement;
    await user.click(row);

    await waitFor(() => {
      // "All" merges duplicates so multiple detail panels may expand
      expect(screen.getAllByText('Content').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Metadata').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('source').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('empty collection shows empty state', async () => {
    mockFetchKbDocuments.mockResolvedValue({
      documents: [],
      total: 0,
      has_more: false,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('No documents in this collection.')).toBeInTheDocument();
    });
  });

  it('loading state displayed during fetch', async () => {
    // Collections resolve immediately so targetCollections is populated
    mockFetchKbCollections.mockResolvedValue({
      collections: [{ name: 'long_term_document', count: 1 }],
    });

    // Document fetch hangs to keep loading state visible
    let resolvePromise: (value: unknown) => void;
    mockFetchKbDocuments.mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve;
      }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    // Resolve to clean up
    resolvePromise!({
      documents: [],
      total: 0,
      has_more: false,
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });
  });

  it('error state on API failure', async () => {
    mockFetchKbDocuments.mockRejectedValue(new Error('Network error'));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('load more button appends next page', async () => {
    const user = userEvent.setup();

    // First page
    mockFetchKbDocuments
      .mockResolvedValueOnce({
        documents: [
          { id: 'page1-a', document: 'First page doc', metadata: {} },
        ],
        total: 2,
        has_more: true,
      })
      .mockResolvedValueOnce({
        documents: [
          { id: 'page1-b', document: 'First page doc 2', metadata: {} },
        ],
        total: 2,
        has_more: true,
      });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Load more')).toBeInTheDocument();
    });

    // Second page
    mockFetchKbDocuments
      .mockResolvedValueOnce({
        documents: [
          { id: 'page2-a', document: 'Second page doc', metadata: {} },
        ],
        total: 2,
        has_more: false,
      })
      .mockResolvedValueOnce({
        documents: [],
        total: 0,
        has_more: false,
      });

    await user.click(screen.getByText('Load more'));

    await waitFor(() => {
      expect(screen.queryByText('Load more')).not.toBeInTheDocument();
    });
  });
});
