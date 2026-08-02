import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StatusTransition } from '../../components/StatusTransition';

describe('StatusTransition', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders dropdown with valid transition options only', () => {
    render(
      <StatusTransition
        epicId="EPIC-001"
        currentStatus="in_progress"
        validTransitions={['completed', 'abandoned']}
        onStatusChange={vi.fn()}
      />,
    );

    const select = screen.getByLabelText('Change epic status');
    const options = select.querySelectorAll('option');
    // 1 disabled current-status option + 2 transition options
    expect(options).toHaveLength(3);
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Abandoned')).toBeInTheDocument();
  });

  it('selecting a transition calls the API mutation endpoint', async () => {
    const user = userEvent.setup();
    fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);

    render(
      <StatusTransition
        epicId="EPIC-001"
        currentStatus="in_progress"
        validTransitions={['completed', 'abandoned']}
        onStatusChange={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText('Change epic status'), 'completed');

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/epics/EPIC-001/status',
        expect.objectContaining({ method: 'PATCH' }),
      );
    });
  });

  it('calls onStatusChange callback after successful mutation', async () => {
    const user = userEvent.setup();
    fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const onStatusChange = vi.fn();

    render(
      <StatusTransition
        epicId="EPIC-001"
        currentStatus="in_progress"
        validTransitions={['completed']}
        onStatusChange={onStatusChange}
      />,
    );

    await user.selectOptions(screen.getByLabelText('Change epic status'), 'completed');

    await waitFor(() => {
      expect(onStatusChange).toHaveBeenCalledWith('completed');
    });
  });

  it('dropdown is disabled when validTransitions is empty', () => {
    render(
      <StatusTransition
        epicId="EPIC-001"
        currentStatus="completed"
        validTransitions={[]}
        onStatusChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Change epic status')).toBeDisabled();
  });

  it('dropdown is disabled while save is in flight', async () => {
    const user = userEvent.setup();
    // Create a deferred promise to control when fetch resolves
    let resolveFetch!: (value: Response) => void;
    fetchSpy = vi.fn().mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);

    render(
      <StatusTransition
        epicId="EPIC-001"
        currentStatus="in_progress"
        validTransitions={['completed']}
        onStatusChange={vi.fn()}
      />,
    );

    const select = screen.getByLabelText('Change epic status');
    expect(select).not.toBeDisabled();

    await user.selectOptions(select, 'completed');

    // While fetch is pending, the select should be disabled
    await waitFor(() => {
      expect(select).toBeDisabled();
    });

    // Resolve the fetch
    resolveFetch(
      new Response(JSON.stringify({ success: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    // After resolve, the select should be re-enabled
    await waitFor(() => {
      expect(select).not.toBeDisabled();
    });
  });

  it('API error renders error message in status-transition__error', async () => {
    const user = userEvent.setup();
    fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Transition not allowed' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);

    const { container } = render(
      <StatusTransition
        epicId="EPIC-001"
        currentStatus="in_progress"
        validTransitions={['completed']}
        onStatusChange={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText('Change epic status'), 'completed');

    await waitFor(() => {
      const errorEl = container.querySelector('.status-transition__error');
      expect(errorEl).toBeInTheDocument();
      expect(errorEl).toHaveTextContent('Transition not allowed');
    });
  });
});
