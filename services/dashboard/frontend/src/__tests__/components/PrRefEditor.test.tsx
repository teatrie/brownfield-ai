import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { PrRefEditor } from '../../components/PrRefEditor';
import { setEpicPrs, clearEpicPrs } from '../../api/client';

vi.mock('../../api/client', () => ({
  setEpicPrs: vi.fn(),
  clearEpicPrs: vi.fn(),
}));

describe('PrRefEditor', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders current PRs text when provided', () => {
    render(
      <PrRefEditor epicId="EPIC-001" currentPrs="owner/repo#42" onUpdate={vi.fn()} />,
    );

    expect(screen.getByText('owner/repo#42')).toBeInTheDocument();
  });

  it('renders "No PRs" when currentPrs is null', () => {
    render(
      <PrRefEditor epicId="EPIC-001" currentPrs={null} onUpdate={vi.fn()} />,
    );

    expect(screen.getByText('No PRs')).toBeInTheDocument();
  });

  it('clicking Edit shows input field with aria-label "PR reference"', async () => {
    const user = userEvent.setup();
    render(
      <PrRefEditor epicId="EPIC-001" currentPrs="owner/repo#42" onUpdate={vi.fn()} />,
    );

    await user.click(screen.getByText('Edit'));

    expect(screen.getByLabelText('PR reference')).toBeInTheDocument();
  });

  it('typing a value and clicking Save calls setEpicPrs and shows toast', async () => {
    const user = userEvent.setup();
    vi.mocked(setEpicPrs).mockResolvedValue({ success: true });
    const onUpdate = vi.fn();
    render(
      <PrRefEditor epicId="EPIC-001" currentPrs={null} onUpdate={onUpdate} />,
    );

    await user.click(screen.getByText('Edit'));
    const input = screen.getByLabelText('PR reference');
    await user.type(input, 'owner/repo#99');
    await user.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(setEpicPrs).toHaveBeenCalledWith('EPIC-001', 'owner/repo#99');
    });
    await waitFor(() => {
      expect(screen.getByText('PR references updated')).toBeInTheDocument();
    });
  });

  it('clicking Clear calls clearEpicPrs and calls onUpdate(null)', async () => {
    const user = userEvent.setup();
    vi.mocked(clearEpicPrs).mockResolvedValue({ success: true });
    const onUpdate = vi.fn();
    render(
      <PrRefEditor epicId="EPIC-002" currentPrs="owner/repo#1" onUpdate={onUpdate} />,
    );

    await user.click(screen.getByText('Edit'));
    await user.click(screen.getByText('Clear'));

    await waitFor(() => {
      expect(clearEpicPrs).toHaveBeenCalledWith('EPIC-002');
    });
    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(null);
    });
  });

  it('clicking Cancel restores view mode', async () => {
    const user = userEvent.setup();
    render(
      <PrRefEditor epicId="EPIC-001" currentPrs="owner/repo#42" onUpdate={vi.fn()} />,
    );

    await user.click(screen.getByText('Edit'));
    expect(screen.getByLabelText('PR reference')).toBeInTheDocument();

    await user.click(screen.getByText('Cancel'));
    expect(screen.queryByLabelText('PR reference')).not.toBeInTheDocument();
    expect(screen.getByText('owner/repo#42')).toBeInTheDocument();
  });

  it('Save button is disabled while saving is true', async () => {
    const user = userEvent.setup();
    vi.mocked(setEpicPrs).mockReturnValue(new Promise(() => {}));
    render(
      <PrRefEditor epicId="EPIC-001" currentPrs={null} onUpdate={vi.fn()} />,
    );

    await user.click(screen.getByText('Edit'));
    const input = screen.getByLabelText('PR reference');
    await user.type(input, 'owner/repo#1');
    await user.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(screen.getByText('Save')).toBeDisabled();
    });
  });

  it('Save button is disabled when draft is empty or whitespace only', async () => {
    const user = userEvent.setup();
    render(
      <PrRefEditor epicId="EPIC-001" currentPrs={null} onUpdate={vi.fn()} />,
    );

    await user.click(screen.getByText('Edit'));
    const saveBtn = screen.getByText('Save');
    expect(saveBtn).toBeDisabled();

    const input = screen.getByLabelText('PR reference');
    await user.type(input, '   ');
    expect(saveBtn).toBeDisabled();
  });

  it('when setEpicPrs rejects error message renders in .pr-ref-editor__error', async () => {
    const user = userEvent.setup();
    vi.mocked(setEpicPrs).mockRejectedValue(new Error('Network failure'));
    const { container } = render(
      <PrRefEditor epicId="EPIC-001" currentPrs={null} onUpdate={vi.fn()} />,
    );

    await user.click(screen.getByText('Edit'));
    const input = screen.getByLabelText('PR reference');
    await user.type(input, 'owner/repo#1');
    await user.click(screen.getByText('Save'));

    await waitFor(() => {
      const errorEl = container.querySelector('.pr-ref-editor__error');
      expect(errorEl).toBeInTheDocument();
      expect(errorEl).toHaveTextContent('Network failure');
    });
  });
});
