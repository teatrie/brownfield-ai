import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PriorityEditor } from '../../components/PriorityEditor';

describe('PriorityEditor', () => {
  it('displays current priority value as text', () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    expect(screen.getByText('P5')).toBeInTheDocument();
  });

  it('click enters edit mode rendering input with aria-label', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    await user.click(screen.getByText('P5'));

    expect(screen.getByLabelText('Edit priority')).toBeInTheDocument();
  });

  it('enter key calls onSave with parsed number', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    await user.click(screen.getByText('P5'));
    const input = screen.getByLabelText('Edit priority');
    await user.clear(input);
    await user.type(input, '3');
    await user.keyboard('{Enter}');

    expect(onSave).toHaveBeenCalledWith(3);
  });

  it('escape key cancels edit mode without calling onSave', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    await user.click(screen.getByText('P5'));
    await user.keyboard('{Escape}');

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText('P5')).toBeInTheDocument();
  });

  it('out-of-range input resets without calling onSave', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    await user.click(screen.getByText('P5'));
    const input = screen.getByLabelText('Edit priority');
    await user.clear(input);
    await user.type(input, '15');
    await user.keyboard('{Enter}');

    expect(onSave).not.toHaveBeenCalled();
  });

  it('NaN input resets without calling onSave', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    await user.click(screen.getByText('P5'));
    const input = screen.getByLabelText('Edit priority') as HTMLInputElement;

    // Temporarily switch to text type so jsdom accepts non-numeric value,
    // then simulate the onChange to set draft to 'abc' (produces NaN).
    input.type = 'text';
    fireEvent.change(input, { target: { value: 'abc' } });
    input.type = 'number';

    await user.keyboard('{Enter}');

    expect(onSave).not.toHaveBeenCalled();
  });

  it('blur triggers save via commitValue', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    await user.click(screen.getByText('P5'));
    const input = screen.getByLabelText('Edit priority');
    await user.clear(input);
    await user.type(input, '7');
    await user.tab();

    expect(onSave).toHaveBeenCalledWith(7);
  });

  it('same-value submit is no-op and does not call onSave', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<PriorityEditor value={5} onSave={onSave} />);

    await user.click(screen.getByText('P5'));
    // Draft is already "5", just press enter
    await user.keyboard('{Enter}');

    expect(onSave).not.toHaveBeenCalled();
  });
});
