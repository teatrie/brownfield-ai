/**
 * Tests for the HomePage component.
 *
 * Validates stat card rendering, navigation links, loading state,
 * error state, and null activity handling.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { HomePage } from './HomePage';
import type { HomeStats } from '../types';

// Mock the API client module
vi.mock('../api/client', () => ({
  fetchHomeStats: vi.fn(),
}));

import { fetchHomeStats } from '../api/client';
const mockFetchHomeStats = vi.mocked(fetchHomeStats);

const MOCK_STATS: HomeStats = {
  epics: {
    by_status: {
      in_progress: 9,
      completed: 17,
      backlog: 7,
      blocked: 11,
      approved: 14,
      pending: 0,
      in_review: 16,
      abandoned: 0,
    },
    active: 3,
    blocked: 1,
    completed_24h: 2,
    created_24h: 15,
    total: 13,
  },
  todos: {
    open: 8,
    assigned: 4,
    done: 12,
    total: 23,
    high_priority_open: 2,
    by_category: [
      { category: 'infra', count: 19 },
      { category: 'code', count: 18 },
    ],
  },
  activity: {
    artifacts_1h: 5,
    artifacts_24h: 25,
    gates_24h: { pass: 6, fail: 10 },
    prs_created_7d: 20,
    prs_merged_7d: 21,
  },
};

function renderHomePage() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <HomePage />
    </MemoryRouter>,
  );
}

describe('HomePage', () => {
  beforeEach(() => {
    mockFetchHomeStats.mockReset();
  });

  it('shows loading state initially', () => {
    mockFetchHomeStats.mockReturnValue(new Promise(() => {})); // never resolves
    renderHomePage();
    expect(screen.getByText('Loading stats...')).toBeInTheDocument();
  });

  it('renders epic stats after loading', async () => {
    mockFetchHomeStats.mockResolvedValue(MOCK_STATS);
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });

    // Total epics
    expect(screen.getByText('13')).toBeInTheDocument();
    // Active
    expect(screen.getByText('3')).toBeInTheDocument();
    // Blocked
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('renders todo stats', async () => {
    mockFetchHomeStats.mockResolvedValue(MOCK_STATS);
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });

    // Total todos
    expect(screen.getByText('23')).toBeInTheDocument();
    // Open
    expect(screen.getByText('8')).toBeInTheDocument();
    // High priority
    expect(screen.getByText('High Priority')).toBeInTheDocument();
  });

  it('renders activity stats', async () => {
    mockFetchHomeStats.mockResolvedValue(MOCK_STATS);
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });

    expect(screen.getByText('Artifacts 24h')).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
    expect(screen.getByText('Gates Pass 24h')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
  });

  it('renders category tags', async () => {
    mockFetchHomeStats.mockResolvedValue(MOCK_STATS);
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('infra')).toBeInTheDocument();
    });

    expect(screen.getByText('code')).toBeInTheDocument();
  });

  it('shows error indicator when activity is null', async () => {
    const statsWithNullActivity: HomeStats = {
      ...MOCK_STATS,
      activity: null,
    };
    mockFetchHomeStats.mockResolvedValue(statsWithNullActivity);
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });

    expect(
      screen.getByText('Activity data unavailable (ChromaDB unreachable)'),
    ).toBeInTheDocument();
  });

  it('shows error state on API failure', async () => {
    mockFetchHomeStats.mockRejectedValue(new Error('Network error'));
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('renders navigation links to filtered views', async () => {
    mockFetchHomeStats.mockResolvedValue(MOCK_STATS);
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });

    // Check that links exist pointing to filtered views
    const links = screen.getAllByRole('link');
    const hrefs = links.map((l) => l.getAttribute('href'));
    expect(hrefs).toContain('/epics');
    expect(hrefs).toContain('/epics?status=blocked');
    expect(hrefs).toContain('/todos?status=open');
    expect(hrefs).toContain('/timeline/all');
  });

  it('renders correct hrefs for all filterable stat cards', async () => {
    mockFetchHomeStats.mockResolvedValue(MOCK_STATS);
    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });

    const links = screen.getAllByRole('link');
    const hrefs = links.map((l) => l.getAttribute('href'));

    // Epic stat cards with working filters
    expect(hrefs).toContain('/epics');
    expect(hrefs).toContain('/epics?status=in_progress');
    expect(hrefs).toContain('/epics?status=blocked');
    expect(hrefs).toContain('/epics?status=completed');
    expect(hrefs).toContain('/epics?status=in_review');
    expect(hrefs).toContain('/epics?status=approved');
    expect(hrefs).toContain('/epics?status=pending');
    expect(hrefs).toContain('/epics?status=backlog');
    expect(hrefs).toContain('/epics?status=abandoned');

    // TODO stat cards with working filters
    expect(hrefs).toContain('/todos?status=all');
    expect(hrefs).toContain('/todos?status=open');
    expect(hrefs).toContain('/todos?status=assigned');
    expect(hrefs).toContain('/todos?status=done');
    expect(hrefs).toContain('/todos?status=open&sort=priority&order=asc');

    // Category tags with working filters
    expect(hrefs).toContain('/todos?status=open&category=infra');
    expect(hrefs).toContain('/todos?status=open&category=code');
  });
});
