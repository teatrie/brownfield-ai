import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { Layout } from '../../components/Layout';

describe('Layout', () => {
  it('renders sidebar with 5 nav links', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole('link', { name: /Epics/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Timeline/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /TODOs/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Search/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Knowledge/ })).toBeInTheDocument();
  });

  it('collapse toggle changes aria-label from Collapse to Expand', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const toggleBtn = screen.getByRole('button', { name: 'Collapse sidebar' });
    expect(toggleBtn).toBeInTheDocument();

    await user.click(toggleBtn);

    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();
  });

  it('NavLink has active class when on matching route', () => {
    render(
      <MemoryRouter initialEntries={['/epics']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/epics" element={<div />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const epicsLink = screen.getByRole('link', { name: /Epics/ });
    expect(epicsLink).toHaveClass('nav-link--active');
  });

  it('Outlet renders child route content', () => {
    render(
      <MemoryRouter initialEntries={['/epics']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/epics" element={<div data-testid="child-content">Epics Page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('child-content')).toBeInTheDocument();
  });

  it('ThemeToggle renders in the header, not the sidebar', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const themeBtn = screen.getByRole('button', { name: /switch to/i });
    expect(themeBtn.closest('.header__actions')).toBeInTheDocument();
  });

  it('collapsed sidebar still exposes nav links with aria-label', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }));

    // Nav links remain accessible by aria-label even when labels are visually hidden
    expect(screen.getByRole('link', { name: 'Epics' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Timeline' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'TODOs' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Search' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Knowledge' })).toBeInTheDocument();
  });

  it('edge toggle has aria-expanded matching sidebar state', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const toggle = screen.getByRole('button', { name: 'Collapse sidebar' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    await user.click(toggle);

    const expandToggle = screen.getByRole('button', { name: 'Expand sidebar' });
    expect(expandToggle).toHaveAttribute('aria-expanded', 'false');
  });
});
