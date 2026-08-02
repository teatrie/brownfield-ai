import { render } from '@testing-library/react';
import { StateMachine } from '../../components/StateMachine';

const transitions: Record<string, string[]> = {
  in_progress: ['completed', 'abandoned', 'approved'],
};

describe('StateMachine', () => {
  it('renders a node for each of the 8 epic statuses', () => {
    const { container } = render(
      <StateMachine currentStatus="in_progress" transitions={transitions} />,
    );

    const nodes = container.querySelectorAll('.state-node');
    expect(nodes).toHaveLength(8);
  });

  it('highlights currentStatus node with state-node--current class', () => {
    const { container } = render(
      <StateMachine currentStatus="in_progress" transitions={transitions} />,
    );

    const currentNodes = container.querySelectorAll('.state-node--current');
    expect(currentNodes).toHaveLength(1);
    expect(currentNodes[0]).toHaveTextContent('In Progress');
  });

  it('renders state-arrow elements for valid transition targets', () => {
    const { container } = render(
      <StateMachine currentStatus="in_progress" transitions={transitions} />,
    );

    const arrows = container.querySelectorAll('.state-arrow');
    expect(arrows).toHaveLength(3);
  });

  it('renders zero arrows and no target nodes when transitions is empty', () => {
    const { container } = render(
      <StateMachine currentStatus="in_progress" transitions={{}} />,
    );

    const arrows = container.querySelectorAll('.state-arrow');
    expect(arrows).toHaveLength(0);

    const targetNodes = container.querySelectorAll('.state-node--target');
    expect(targetNodes).toHaveLength(0);
  });

  it('terminal states get state-node--terminal CSS class', () => {
    const { container } = render(
      <StateMachine currentStatus="in_progress" transitions={transitions} />,
    );

    const terminalNodes = container.querySelectorAll('.state-node--terminal');
    expect(terminalNodes).toHaveLength(2);

    const labels = Array.from(terminalNodes).map((n) => n.textContent);
    expect(labels.some((l) => l?.includes('Completed'))).toBe(true);
    expect(labels.some((l) => l?.includes('Abandoned'))).toBe(true);
  });
});
