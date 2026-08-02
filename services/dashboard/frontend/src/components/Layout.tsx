import { useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { SearchBar } from './SearchBar';
import { ThemeToggle } from './ThemeToggle';

/** Icon + label pairs for sidebar navigation entries. */
const NAV_ITEMS = [
  { to: '/', icon: '\uD83C\uDFE0', label: 'Home' },
  { to: '/epics', icon: '\uD83D\uDCCB\uFE0F', label: 'Epics' },
  { to: '/timeline/all', icon: '\u23F3\uFE0F', label: 'Timeline' },
  { to: '/todos', icon: '\u2714\uFE0F', label: 'TODOs' },
  { to: '/search', icon: '\uD83D\uDD0D\uFE0F', label: 'Search' },
  { to: '/knowledge', icon: '\uD83D\uDCDA\uFE0F', label: 'Knowledge' },
] as const;

/**
 * Shell layout with collapsible sidebar, header bar, and main content area.
 *
 * Provides the 3-zone layout structure: left sidebar (220px open / 56px
 * collapsed) with navigation icons, a header bar (48px) with SearchBar and
 * ThemeToggle, and main content rendered via React Router Outlet.  The
 * sidebar collapse toggle is an edge-chevron pill anchored to the sidebar's
 * right border so the "Ledger" title remains visible in both states.
 */
export function Layout(): React.JSX.Element {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="layout">
      <aside
        id="sidebar"
        className={`sidebar ${sidebarOpen ? 'sidebar--open' : 'sidebar--collapsed'}`}
      >
        <div className="sidebar__header">
          <Link to="/" className="sidebar__title" title="Ledger" aria-label="Ledger home">
            <span className="sidebar__title-icon" aria-hidden="true">{'\uD83C\uDF0A'}</span>
            <span className="sidebar__title-label">Ledger</span>
          </Link>
        </div>
        <nav className="sidebar__nav">
          {NAV_ITEMS.map(({ to, icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              title={label}
              aria-label={label}
              className={({ isActive }) =>
                `nav-link ${isActive ? 'nav-link--active' : ''}`
              }
            >
              <span className="nav-link__icon" aria-hidden="true">{icon}</span>
              <span className="nav-link__label">{label}</span>
            </NavLink>
          ))}
        </nav>
        <button
          className="sidebar__edge-toggle"
          onClick={() => setSidebarOpen((prev) => !prev)}
          aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          aria-expanded={sidebarOpen}
          aria-controls="sidebar"
        >
          {sidebarOpen ? '\u2039' : '\u203A'}
        </button>
      </aside>
      <div className="main-area">
        <header className="header">
          <div className="header__spacer" />
          <div className="header__search">
            <SearchBar />
          </div>
          <div className="header__actions">
            <ThemeToggle />
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
