import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SearchResult } from '../../components/SearchResult';
import type { TodoItem } from '../../types';

vi.mock('../../api/client', () => ({
  fetchTodoById: vi.fn(),
}));

import { fetchTodoById } from '../../api/client';

interface RenderProps {
  source?: 'artifact' | 'todo' | 'epic';
  id?: string;
  document?: string;
  metadata?: Record<string, unknown>;
  distance?: number;
  query?: string;
}

function renderResult(props: RenderProps = {}) {
  const {
    source = 'artifact',
    id = 'test-id-1',
    document = 'This is the test document content',
    metadata = {},
    distance = 0.5,
    query = 'test',
  } = props;

  return render(
    <MemoryRouter>
      <SearchResult
        source={source}
        id={id}
        document={document}
        metadata={metadata}
        distance={distance}
        query={query}
      />
    </MemoryRouter>,
  );
}

describe('SearchResult', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('(a) renders artifact source with clickable class and Artifact label', () => {
    const { container } = renderResult({ source: 'artifact' });

    expect(screen.getByText('Artifact')).toBeInTheDocument();
    expect(container.querySelector('.search-result--clickable')).toBeInTheDocument();
  });

  it('(b) renders todo source with expand/collapse and lazy-loads detail', async () => {
    const user = userEvent.setup();
    const todoDetail: TodoItem = {
      id: 42,
      title: 'Fix the bug',
      status: 'open',
      priority: 3,
      description: 'Detailed description here',
      epic_id: 'EPIC-001',
    };

    vi.mocked(fetchTodoById).mockResolvedValue(todoDetail);

    renderResult({ source: 'todo', id: '42' });

    const resultEl = document.querySelector('.search-result')!;
    await user.click(resultEl as HTMLElement);

    expect(fetchTodoById).toHaveBeenCalledWith(42);

    await waitFor(() =>
      expect(screen.getByText('Detailed description here')).toBeInTheDocument(),
    );
  });

  it('(c) renders epic source with Epic label and clickable class', () => {
    const { container } = renderResult({ source: 'epic', id: 'EPIC-001' });

    expect(screen.getByText('Epic')).toBeInTheDocument();
    expect(container.querySelector('.search-result--clickable')).toBeInTheDocument();
  });

  it('(d) highlightTerms wraps matching query word in mark element', () => {
    renderResult({
      source: 'artifact',
      document: 'This is a test document for search',
      query: 'test',
    });

    const mark = document.querySelector('mark');
    expect(mark).toBeInTheDocument();
    expect(mark?.textContent).toBe('test');
  });

  it('(e) relevancePercent: distance=0 → 100%, distance=2 → 0%, distance=1 → 50%', () => {
    const { container: c1 } = renderResult({ distance: 0 });
    const bar1 = c1.querySelector('.search-result__distance-bar') as HTMLElement;
    expect(bar1.style.width).toBe('100%');

    const { container: c2 } = renderResult({ distance: 2 });
    const bar2 = c2.querySelector('.search-result__distance-bar') as HTMLElement;
    expect(bar2.style.width).toBe('0%');

    const { container: c3 } = renderResult({ distance: 1 });
    const bar3 = c3.querySelector('.search-result__distance-bar') as HTMLElement;
    expect(bar3.style.width).toBe('50%');
  });

  it('(f) sessionStorage write on click for artifact result', async () => {
    const user = userEvent.setup();
    renderResult({
      source: 'artifact',
      query: 'my-search-query',
      metadata: { epic_id: 'EPIC-001' },
    });

    const resultEl = document.querySelector('.search-result--clickable')!;
    await user.click(resultEl as HTMLElement);

    expect(sessionStorage.getItem('lastSearchQuery')).toBe('my-search-query');
  });

  it('(g) keyboard Enter on artifact result writes sessionStorage', async () => {
    const user = userEvent.setup();
    renderResult({
      source: 'artifact',
      query: 'keyboard-query',
      metadata: { epic_id: 'EPIC-002' },
    });

    const resultEl = document.querySelector('.search-result')!;
    (resultEl as HTMLElement).focus();
    await user.keyboard('{Enter}');

    expect(sessionStorage.getItem('lastSearchQuery')).toBe('keyboard-query');
  });

  it('(g2) keyboard Space on artifact result writes sessionStorage', async () => {
    const user = userEvent.setup();
    renderResult({
      source: 'artifact',
      query: 'space-query',
      metadata: { epic_id: 'EPIC-003' },
    });

    const resultEl = document.querySelector('.search-result')!;
    (resultEl as HTMLElement).focus();
    await user.keyboard(' ');

    expect(sessionStorage.getItem('lastSearchQuery')).toBe('space-query');
  });

  it('(h) aria-expanded toggles on todo result click', async () => {
    const user = userEvent.setup();
    vi.mocked(fetchTodoById).mockResolvedValue({
      id: 1,
      title: 'Test todo',
      status: 'open',
      priority: 1,
    });

    renderResult({ source: 'todo', id: '1' });

    const resultEl = document.querySelector('.search-result')!;
    expect(resultEl).toHaveAttribute('aria-expanded', 'false');

    await user.click(resultEl as HTMLElement);
    expect(resultEl).toHaveAttribute('aria-expanded', 'true');
  });

  it('(i) fetchTodoById rejection shows error in .error-message', async () => {
    const user = userEvent.setup();
    vi.mocked(fetchTodoById).mockRejectedValue(new Error('Network failure'));

    renderResult({ source: 'todo', id: '99' });

    const resultEl = document.querySelector('.search-result')!;
    await user.click(resultEl as HTMLElement);

    await waitFor(() => {
      const errorEl = document.querySelector('.error-message');
      expect(errorEl).toBeInTheDocument();
      expect(errorEl?.textContent).toBe('Network failure');
    });
  });
});
