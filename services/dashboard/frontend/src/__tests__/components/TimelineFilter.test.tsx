import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimelineFilter } from '../../components/TimelineFilter';
import type { TimelineFilters } from '../../components/TimelineFilter';

const defaultFilters: TimelineFilters = {
  artifactType: '',
  wave: '',
  domain: '',
  verdict: '',
};

describe('TimelineFilter', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders 12 artifact type pill buttons', () => {
    const { container } = render(
      <TimelineFilter filters={defaultFilters} onFilterChange={vi.fn()} />,
    );

    const pills = container.querySelectorAll('.filter-pill');
    expect(pills).toHaveLength(12);
  });

  it('clicking a pill sets artifactType and clicking again clears it', async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    const { rerender } = render(
      <TimelineFilter filters={defaultFilters} onFilterChange={onFilterChange} />,
    );

    const pill = screen.getByText('Plan Snapshot');
    await user.click(pill);
    expect(onFilterChange).toHaveBeenLastCalledWith({
      ...defaultFilters,
      artifactType: 'plan_snapshot',
    });

    const updatedFilters: TimelineFilters = { ...defaultFilters, artifactType: 'plan_snapshot' };
    rerender(<TimelineFilter filters={updatedFilters} onFilterChange={onFilterChange} />);

    await user.click(pill);
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...defaultFilters, artifactType: '' });
  });

  it('wave text input fires onFilterChange with updated wave value', async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    render(<TimelineFilter filters={defaultFilters} onFilterChange={onFilterChange} />);

    const waveInput = screen.getByPlaceholderText('Wave');
    await user.type(waveInput, 'w');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...defaultFilters, wave: 'w' });
  });

  it('domain text input fires onFilterChange with updated domain value', async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    render(<TimelineFilter filters={defaultFilters} onFilterChange={onFilterChange} />);

    const domainInput = screen.getByPlaceholderText('Domain');
    await user.type(domainInput, 'd');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...defaultFilters, domain: 'd' });
  });

  it('verdict dropdown renders 4 options and changing selection fires onFilterChange', async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    const { container } = render(
      <TimelineFilter filters={defaultFilters} onFilterChange={onFilterChange} />,
    );

    const select = container.querySelector('.filter-dropdown') as HTMLSelectElement;
    const options = select.querySelectorAll('option');
    expect(options).toHaveLength(4);
    expect(options[0]).toHaveTextContent('All Verdicts');
    expect(options[1]).toHaveTextContent('GREEN');
    expect(options[2]).toHaveTextContent('FAIL');
    expect(options[3]).toHaveTextContent('RETRY');

    await user.selectOptions(select, 'GREEN');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...defaultFilters, verdict: 'GREEN' });
  });

  it('formatType produces "Plan Snapshot" label for "plan_snapshot" type', () => {
    render(<TimelineFilter filters={defaultFilters} onFilterChange={vi.fn()} />);
    expect(screen.getByText('Plan Snapshot')).toBeInTheDocument();
  });
});
