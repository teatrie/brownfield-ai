import { render, screen } from '@testing-library/react';
import { InfoTip } from '../../components/InfoTip';

describe('InfoTip', () => {
  it('renders element with data-tooltip attribute matching text prop', () => {
    render(<InfoTip text="Help text here" />);

    const tip = screen.getByText('i');
    expect(tip).toHaveAttribute('data-tooltip', 'Help text here');
  });

  it('renders the info icon text content', () => {
    render(<InfoTip text="Some tooltip" />);

    expect(screen.getByText('i')).toBeInTheDocument();
  });
});
