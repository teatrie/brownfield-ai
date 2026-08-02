import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { TodoItemRow } from '../../components/TodoItem';
import type { TodoItem } from '../../types';

const baseTodo: TodoItem = {
  id: 1,
  title: 'Fix the login bug',
  status: 'open',
  priority: 3,
  description: 'Users cannot log in on mobile devices.',
  category: 'bug',
  epic_id: 'EPIC-001',
};

/** Render TodoItemRow within a MemoryRouter. */
function renderRow(todo: TodoItem, onUpdate?: () => void) {
  return render(
    <MemoryRouter>
      <TodoItemRow todo={todo} onUpdate={onUpdate} />
    </MemoryRouter>,
  );
}

describe('TodoItemRow', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders title and priority for a TODO item', () => {
    renderRow(baseTodo);

    expect(screen.getByText('Fix the login bug')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders zero-padded TODO ID badge', () => {
    renderRow(baseTodo);

    expect(screen.getByText('TODO-0001')).toBeInTheDocument();
  });

  it('expand toggle reveals description section', async () => {
    const user = userEvent.setup();
    renderRow(baseTodo);

    const toggleDiv = document.querySelector('.todo-item__toggle')!;
    await user.click(toggleDiv);

    expect(screen.getByText('Users cannot log in on mobile devices.')).toBeInTheDocument();
  });

  it('expand via keyboard Enter and Space on toggle div', async () => {
    const user = userEvent.setup();
    renderRow(baseTodo);

    const toggleDiv = document.querySelector('.todo-item__toggle')!;

    // Focus the toggle and press Enter
    (toggleDiv as HTMLElement).focus();
    await user.keyboard('{Enter}');
    expect(screen.getByText('Users cannot log in on mobile devices.')).toBeInTheDocument();

    // Press Space to collapse
    await user.keyboard(' ');
    expect(screen.queryByText('Users cannot log in on mobile devices.')).not.toBeInTheDocument();
  });

  it('category badge renders when todo.category is set, absent when undefined', () => {
    const { container, unmount } = renderRow(baseTodo);
    expect(container.querySelector('.todo-item__category')).toBeInTheDocument();
    unmount();

    const noCategoryTodo: TodoItem = { ...baseTodo, category: undefined };
    const { container: container2 } = renderRow(noCategoryTodo);
    expect(container2.querySelector('.todo-item__category')).not.toBeInTheDocument();
  });

  it('expanded section renders Link when epic_id is present', async () => {
    const user = userEvent.setup();
    renderRow(baseTodo);

    const toggleDiv = document.querySelector('.todo-item__toggle')!;
    await user.click(toggleDiv);

    const epicLink = screen.getByText('EPIC-001');
    expect(epicLink.closest('a')).toHaveAttribute('href', '/epics/EPIC-001');
  });

  it('action buttons render conditionally by status when onUpdate is provided', () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ));

    const { container } = renderRow(baseTodo, vi.fn());
    expect(container.querySelector('.todo-actions')).toBeInTheDocument();
  });

  it('priority update calls updateTodoPriority API via the component chain', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ success: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const todo: TodoItem = { id: 1, title: 'Test', status: 'open', priority: 5 };
    const onUpdate = vi.fn();
    renderRow(todo, onUpdate);

    // Find and click the priority pill to enter edit mode
    const pill = screen.getByLabelText('Priority 5, click to edit');
    await user.click(pill);

    // Edit the priority value
    const input = screen.getByLabelText('Edit priority');
    await user.clear(input);
    await user.type(input, '3');
    await user.keyboard('{Enter}');

    // Verify fetch was called with the correct endpoint
    const fetchMock = vi.mocked(fetch);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/todos/1/priority',
        expect.objectContaining({ method: 'PATCH' }),
      );
    });
  });
});
