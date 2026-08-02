import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ViewModeProvider } from '../../hooks/useViewMode';
import { ViewModeToggle } from '../../components/ViewModeToggle';

describe('ViewModeToggle', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders Markdown and Raw buttons', () => {
    render(
      <ViewModeProvider>
        <ViewModeToggle />
      </ViewModeProvider>,
    );

    expect(screen.getByRole('button', { name: 'Markdown' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Raw' })).toBeInTheDocument();
  });

  it('Markdown button has active class matching context default', () => {
    render(
      <ViewModeProvider>
        <ViewModeToggle />
      </ViewModeProvider>,
    );

    const markdownBtn = screen.getByRole('button', { name: 'Markdown' });
    const rawBtn = screen.getByRole('button', { name: 'Raw' });

    expect(markdownBtn).toHaveClass('view-mode-toggle__btn--active');
    expect(rawBtn).not.toHaveClass('view-mode-toggle__btn--active');
  });

  it('clicking Raw button activates Raw mode', async () => {
    const user = userEvent.setup();
    render(
      <ViewModeProvider>
        <ViewModeToggle />
      </ViewModeProvider>,
    );

    const rawBtn = screen.getByRole('button', { name: 'Raw' });
    await user.click(rawBtn);

    expect(rawBtn).toHaveClass('view-mode-toggle__btn--active');
    expect(screen.getByRole('button', { name: 'Markdown' })).not.toHaveClass(
      'view-mode-toggle__btn--active',
    );
  });

  it('button click does not propagate to parent', async () => {
    const user = userEvent.setup();
    const parentClickSpy = vi.fn();

    render(
      <ViewModeProvider>
        <div onClick={parentClickSpy}>
          <ViewModeToggle />
        </div>
      </ViewModeProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'Markdown' }));
    expect(parentClickSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Raw' }));
    expect(parentClickSpy).not.toHaveBeenCalled();
  });
});
