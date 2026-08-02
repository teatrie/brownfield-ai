import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { SearchBar } from '../../components/SearchBar';

/**
 * Helper component that exposes the current location pathname
 * as a test-id element for assertions.
 */
function LocationDisplay(): React.JSX.Element {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

/** Render SearchBar within MemoryRouter at the given initial path. */
function renderWithRouter(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SearchBar />
      <LocationDisplay />
    </MemoryRouter>,
  );
}

describe('SearchBar', () => {
  it('renders input field with placeholder', () => {
    renderWithRouter();

    expect(screen.getByPlaceholderText('Search... (Cmd+K)')).toBeInTheDocument();
  });

  it('Cmd+K focuses the input', () => {
    renderWithRouter();

    const input = screen.getByPlaceholderText('Search... (Cmd+K)');
    expect(document.activeElement).not.toBe(input);

    fireEvent.keyDown(document, { key: 'k', metaKey: true });

    expect(document.activeElement).toBe(input);
  });

  it('Ctrl+K focuses the input (non-Mac shortcut)', () => {
    renderWithRouter();

    const input = screen.getByPlaceholderText('Search... (Cmd+K)');
    expect(document.activeElement).not.toBe(input);

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });

    expect(document.activeElement).toBe(input);
  });

  it('enter navigates to /search?q=<query>', async () => {
    const user = userEvent.setup();
    renderWithRouter();

    const input = screen.getByPlaceholderText('Search... (Cmd+K)');
    await user.type(input, 'hello');
    await user.keyboard('{Enter}');

    const locationEl = screen.getByTestId('location');
    expect(locationEl.textContent).toContain('/search');
    expect(locationEl.textContent).toContain('q=hello');
  });

  it('empty query on Enter is no-op', async () => {
    const user = userEvent.setup();
    renderWithRouter();

    const input = screen.getByPlaceholderText('Search... (Cmd+K)');
    await user.click(input);
    await user.keyboard('{Enter}');

    const locationEl = screen.getByTestId('location');
    expect(locationEl.textContent).toBe('/');
  });

  it('syncs input value from URL q param on search page', () => {
    renderWithRouter('/search?q=synced');

    const input = screen.getByPlaceholderText('Search... (Cmd+K)');
    expect(input).toHaveValue('synced');
  });

  it('clear button appears when input has text and clears on click', async () => {
    const user = userEvent.setup();
    renderWithRouter();

    const input = screen.getByPlaceholderText('Search... (Cmd+K)');
    expect(screen.queryByLabelText('Clear search')).not.toBeInTheDocument();

    await user.type(input, 'test');
    expect(screen.getByLabelText('Clear search')).toBeInTheDocument();

    await user.click(screen.getByLabelText('Clear search'));
    expect(input).toHaveValue('');
  });

  it('clear button on search page removes q param from URL', async () => {
    const user = userEvent.setup();
    renderWithRouter('/search?q=hello');

    const input = screen.getByPlaceholderText('Search... (Cmd+K)');
    expect(input).toHaveValue('hello');

    await user.click(screen.getByLabelText('Clear search'));

    expect(input).toHaveValue('');
    const locationEl = screen.getByTestId('location');
    expect(locationEl.textContent).toBe('/search');
  });
});
