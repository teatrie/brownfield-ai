import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { TodoActions } from '../../components/TodoActions';
import { assignTodo } from '../../api/client';

vi.mock('../../api/client', () => ({
  assignTodo: vi.fn(),
  updateTodoPriority: vi.fn(),
}));

describe('TodoActions', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('Done button is visible when status is not "done"', () => {
    render(
      <TodoActions
        todoId={1}
        currentStatus="open"
        currentPriority={3}
        onUpdate={vi.fn()}
      />,
    );

    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  it('Done button is hidden when status is "done"', () => {
    render(
      <TodoActions
        todoId={1}
        currentStatus="done"
        currentPriority={3}
        onUpdate={vi.fn()}
      />,
    );

    expect(screen.queryByText('Done')).not.toBeInTheDocument();
  });

  it('clicking Done opens DoneModal', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <TodoActions
        todoId={1}
        currentStatus="open"
        currentPriority={3}
        onUpdate={vi.fn()}
      />,
    );

    await user.click(screen.getByText('Done'));

    expect(container.querySelector('.done-modal__overlay')).toBeInTheDocument();
  });

  it('clicking Assign button shows input with aria-label "Assign to epic"', async () => {
    const user = userEvent.setup();
    render(
      <TodoActions
        todoId={1}
        currentStatus="open"
        currentPriority={3}
        onUpdate={vi.fn()}
      />,
    );

    await user.click(screen.getByText('Assign'));

    expect(screen.getByLabelText('Assign to epic')).toBeInTheDocument();
  });

  it('typing an epic ID and pressing Enter calls assignTodo', async () => {
    const user = userEvent.setup();
    vi.mocked(assignTodo).mockResolvedValue({ success: true });
    const onUpdate = vi.fn();
    render(
      <TodoActions
        todoId={42}
        currentStatus="open"
        currentPriority={3}
        onUpdate={onUpdate}
      />,
    );

    await user.click(screen.getByText('Assign'));
    const input = screen.getByLabelText('Assign to epic');
    await user.type(input, 'EPIC-007');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(assignTodo).toHaveBeenCalledWith(42, 'EPIC-007');
    });
  });

  it('pressing Escape in assign input cancels and input disappears', async () => {
    const user = userEvent.setup();
    render(
      <TodoActions
        todoId={1}
        currentStatus="open"
        currentPriority={3}
        onUpdate={vi.fn()}
      />,
    );

    await user.click(screen.getByText('Assign'));
    expect(screen.getByLabelText('Assign to epic')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByLabelText('Assign to epic')).not.toBeInTheDocument();
  });

  it('PriorityEditor is rendered inline', () => {
    render(
      <TodoActions
        todoId={1}
        currentStatus="open"
        currentPriority={5}
        onUpdate={vi.fn()}
      />,
    );

    // PriorityEditor renders a button showing the current priority value prefixed with "P"
    expect(screen.getByText('P5')).toBeInTheDocument();
  });

  it('blur on empty input cancels and input disappears', async () => {
    const user = userEvent.setup();
    render(
      <TodoActions
        todoId={1}
        currentStatus="open"
        currentPriority={3}
        onUpdate={vi.fn()}
      />,
    );

    await user.click(screen.getByText('Assign'));
    const input = screen.getByLabelText('Assign to epic');
    expect(input).toBeInTheDocument();

    await user.tab();

    expect(screen.queryByLabelText('Assign to epic')).not.toBeInTheDocument();
  });

  it('assign input is disabled while assigning', async () => {
    const user = userEvent.setup();
    vi.mocked(assignTodo).mockReturnValue(new Promise(() => {}));
    render(
      <TodoActions
        todoId={1}
        currentStatus="open"
        currentPriority={3}
        onUpdate={vi.fn()}
      />,
    );

    await user.click(screen.getByText('Assign'));
    const input = screen.getByLabelText('Assign to epic');
    await user.type(input, 'EPIC-001');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(screen.getByLabelText('Assign to epic')).toBeDisabled();
    });
  });
});
