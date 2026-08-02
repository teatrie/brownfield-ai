/**
 * Tests for TodosListPage URL parameter initialization.
 *
 * Verifies that navigating to /todos?status=<value> (and other params)
 * sets the filter controls, confirming stat card links work end-to-end.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TodosListPage } from './TodosListPage';

vi.mock('../api/client', () => ({
  fetchTodos: vi.fn(),
}));

import { fetchTodos } from '../api/client';
const mockFetchTodos = vi.mocked(fetchTodos);

function renderWithRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TodosListPage />
    </MemoryRouter>,
  );
}

describe('TodosListPage URL param filtering', () => {
  beforeEach(() => {
    mockFetchTodos.mockReset();
    mockFetchTodos.mockResolvedValue({ todos: [], total: 0, has_more: false });
  });

  it('defaults to "open" status when no params', async () => {
    renderWithRoute('/todos');

    const select = screen.getByLabelText('Filter by status') as HTMLSelectElement;
    expect(select.value).toBe('open');
  });

  it('initializes status from ?status=done', async () => {
    renderWithRoute('/todos?status=done');

    const select = screen.getByLabelText('Filter by status') as HTMLSelectElement;
    expect(select.value).toBe('done');
  });

  it('initializes status from ?status=all', async () => {
    renderWithRoute('/todos?status=all');

    const select = screen.getByLabelText('Filter by status') as HTMLSelectElement;
    expect(select.value).toBe('all');
  });

  it('initializes status from ?status=assigned', async () => {
    renderWithRoute('/todos?status=assigned');

    const select = screen.getByLabelText('Filter by status') as HTMLSelectElement;
    expect(select.value).toBe('assigned');
  });

  it('initializes category from ?category=infra', async () => {
    mockFetchTodos.mockResolvedValue({
      todos: [
        { id: 1, title: 'Test todo', category: 'infra', status: 'open', priority: 3 },
      ],
      total: 1,
      has_more: false,
    });
    renderWithRoute('/todos?status=open&category=infra');

    await waitFor(() => {
      const select = screen.getByLabelText('Filter by category') as HTMLSelectElement;
      expect(select.value).toBe('infra');
    });
  });

  it('passes URL params to fetchTodos API call', async () => {
    renderWithRoute('/todos?status=done');

    await waitFor(() => {
      expect(mockFetchTodos).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'done' }),
      );
    });
  });

  it('passes sort and order params to fetchTodos', async () => {
    renderWithRoute('/todos?status=open&sort=priority&order=asc');

    await waitFor(() => {
      expect(mockFetchTodos).toHaveBeenCalledWith(
        expect.objectContaining({
          status: 'open',
          sort: 'priority',
          order: 'asc',
        }),
      );
    });
  });
});
