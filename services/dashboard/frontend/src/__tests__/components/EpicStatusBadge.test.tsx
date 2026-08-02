import { render, screen } from '@testing-library/react';
import { EpicStatusBadge } from '../../components/EpicStatusBadge';
import type { EpicStatus } from '../../types';

describe('EpicStatusBadge', () => {
  it('renders badge text matching the status prop', () => {
    render(<EpicStatusBadge status="approved" />);

    expect(screen.getByText('Approved')).toBeInTheDocument();
  });

  it('applies CSS class derived from status', () => {
    render(<EpicStatusBadge status="in_progress" />);

    const badge = screen.getByText('In Progress');
    expect(badge).toHaveClass('status-badge');
    expect(badge).toHaveClass('status-badge--in_progress');
  });

  it('renders correct label and CSS class for all 8 EpicStatus values', () => {
    const expectedLabels: Record<EpicStatus, string> = {
      backlog: 'Backlog',
      pending: 'Pending',
      approved: 'Approved',
      in_progress: 'In Progress',
      in_review: 'In Review',
      completed: 'Completed',
      abandoned: 'Abandoned',
      blocked: 'Blocked',
    };

    for (const status of Object.keys(expectedLabels) as EpicStatus[]) {
      const { unmount } = render(<EpicStatusBadge status={status} />);
      const badge = screen.getByText(expectedLabels[status]);
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveClass(`status-badge--${status}`);
      unmount();
    }
  });

  it('formatStatus produces correct title case for in_progress', () => {
    render(<EpicStatusBadge status="in_progress" />);

    expect(screen.getByText('In Progress')).toBeInTheDocument();
  });
});
