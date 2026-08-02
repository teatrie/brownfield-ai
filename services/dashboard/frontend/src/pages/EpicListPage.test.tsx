/**
 * Tests for EpicListPage URL parameter initialization.
 *
 * Verifies that navigating to /epics?status=<value> sets the active
 * filter pill, confirming stat card links work end-to-end.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EpicListPage } from './EpicListPage';

vi.mock('../api/client', () => ({
  fetchEpics: vi.fn(),
}));

import { fetchEpics } from '../api/client';
const mockFetchEpics = vi.mocked(fetchEpics);

function renderWithRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <EpicListPage />
    </MemoryRouter>,
  );
}

describe('EpicListPage URL param filtering', () => {
  beforeEach(() => {
    mockFetchEpics.mockReset();
    mockFetchEpics.mockResolvedValue({ epics: [], has_more: false });
  });

  it('defaults to "all" filter when no status param', async () => {
    renderWithRoute('/epics');

    await waitFor(() => {
      const allButton = screen.getByRole('button', { name: 'All' });
      expect(allButton).toHaveClass('epic-list__filter--active');
    });
  });

  it('initializes filter from ?status=blocked', async () => {
    renderWithRoute('/epics?status=blocked');

    await waitFor(() => {
      const blockedButton = screen.getByRole('button', { name: 'Blocked' });
      expect(blockedButton).toHaveClass('epic-list__filter--active');
    });

    // "All" should NOT be active
    const allButton = screen.getByRole('button', { name: 'All' });
    expect(allButton).not.toHaveClass('epic-list__filter--active');
  });

  it('initializes filter from ?status=in_progress', async () => {
    renderWithRoute('/epics?status=in_progress');

    await waitFor(() => {
      const button = screen.getByRole('button', { name: 'In Progress' });
      expect(button).toHaveClass('epic-list__filter--active');
    });
  });

  it('initializes filter from ?status=completed', async () => {
    renderWithRoute('/epics?status=completed');

    await waitFor(() => {
      const button = screen.getByRole('button', { name: 'Completed' });
      expect(button).toHaveClass('epic-list__filter--active');
    });
  });

  it('falls back to "all" for invalid status param', async () => {
    renderWithRoute('/epics?status=nonexistent');

    await waitFor(() => {
      const allButton = screen.getByRole('button', { name: 'All' });
      expect(allButton).toHaveClass('epic-list__filter--active');
    });
  });

  it('passes status filter to fetchEpics API call', async () => {
    renderWithRoute('/epics?status=blocked');

    await waitFor(() => {
      expect(mockFetchEpics).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'blocked' }),
      );
    });
  });
});
