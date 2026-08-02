import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DoneModal } from '../../components/DoneModal';

describe('DoneModal', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('submit button is disabled when resolution textarea is empty', () => {
    render(<DoneModal todoId={1} onClose={vi.fn()} onDone={vi.fn()} />);

    expect(screen.getByText('Mark Done')).toBeDisabled();
  });

  it('submitting calls markTodoDone API with resolution text', async () => {
    const user = userEvent.setup();
    fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);

    render(<DoneModal todoId={42} onClose={vi.fn()} onDone={vi.fn()} />);

    await user.type(screen.getByLabelText('Resolution note'), 'Fixed the issue');
    await user.click(screen.getByText('Mark Done'));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/todos/42/done',
        expect.objectContaining({ method: 'PATCH' }),
      );
    });
  });

  it('modal closes after successful submission', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ));
    const onClose = vi.fn();
    const onDone = vi.fn();

    render(<DoneModal todoId={1} onClose={onClose} onDone={onDone} />);

    await user.type(screen.getByLabelText('Resolution note'), 'Resolved');
    await user.click(screen.getByText('Mark Done'));

    await waitFor(() => {
      expect(onDone).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('whitespace-only resolution keeps submit disabled', async () => {
    const user = userEvent.setup();
    render(<DoneModal todoId={1} onClose={vi.fn()} onDone={vi.fn()} />);

    await user.type(screen.getByLabelText('Resolution note'), '   ');

    expect(screen.getByText('Mark Done')).toBeDisabled();
  });

  it('API error keeps modal open and renders error message', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Server error' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }),
    ));
    const onClose = vi.fn();

    const { container } = render(
      <DoneModal todoId={1} onClose={onClose} onDone={vi.fn()} />,
    );

    await user.type(screen.getByLabelText('Resolution note'), 'Resolved');
    await user.click(screen.getByText('Mark Done'));

    await waitFor(() => {
      const errorEl = container.querySelector('.done-modal__error');
      expect(errorEl).toBeInTheDocument();
      expect(errorEl).toHaveTextContent('Server error');
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('overlay click closes modal', () => {
    const onClose = vi.fn();
    const { container } = render(
      <DoneModal todoId={1} onClose={onClose} onDone={vi.fn()} />,
    );

    const overlay = container.querySelector('.done-modal__overlay')!;
    fireEvent.click(overlay);

    expect(onClose).toHaveBeenCalled();
  });

  it('cancel button calls onClose', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<DoneModal todoId={1} onClose={onClose} onDone={vi.fn()} />);

    await user.click(screen.getByText('Cancel'));

    expect(onClose).toHaveBeenCalled();
  });
});
