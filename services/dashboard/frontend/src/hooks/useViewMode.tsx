/**
 * Global view mode context and hook for toggling between
 * rendered Markdown and raw text display of artifact content.
 *
 * Uses React Context (not independent localStorage reads) to
 * ensure all consuming components re-render synchronously
 * when the mode changes.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

/** Supported content view modes. */
export type ViewMode = 'markdown' | 'raw';

/** Storage key for persisting view mode preference. */
const STORAGE_KEY = 'viewMode';

/** Default view mode when no preference is stored. */
const DEFAULT_MODE: ViewMode = 'markdown';

/** Shape of the view mode context value. */
interface ViewModeContextValue {
  /** The current active view mode. */
  viewMode: ViewMode;
  /** Toggle between markdown and raw modes. */
  toggleViewMode: () => void;
  /** Set a specific view mode. */
  setViewMode: (mode: ViewMode) => void;
}

const ViewModeContext = createContext<ViewModeContextValue | null>(null);

/** Props for the ViewModeProvider component. */
interface ViewModeProviderProps {
  /** Child components that may consume the view mode context. */
  children: ReactNode;
}

/**
 * Context provider that owns the single view mode state.
 *
 * Reads the initial mode from localStorage and persists
 * changes back on every update. Wrap the app root in this
 * provider so all descendants share the same mode.
 *
 * @param props - Provider props with children.
 * @returns A context provider element.
 */
export function ViewModeProvider({ children }: ViewModeProviderProps): React.JSX.Element {
  const [viewMode, setViewModeState] = useState<ViewMode>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'markdown' || stored === 'raw' ? stored : DEFAULT_MODE;
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, viewMode);
  }, [viewMode]);

  const toggleViewMode = useCallback(() => {
    setViewModeState((prev) => (prev === 'markdown' ? 'raw' : 'markdown'));
  }, []);

  const setViewMode = useCallback((mode: ViewMode) => {
    setViewModeState(mode);
  }, []);

  return (
    <ViewModeContext.Provider value={{ viewMode, toggleViewMode, setViewMode }}>
      {children}
    </ViewModeContext.Provider>
  );
}

/**
 * Hook to access the global view mode from any descendant.
 *
 * Must be called within a ViewModeProvider. Throws if the
 * context is missing.
 *
 * @returns The view mode value, toggle, and setter.
 */
export function useViewMode(): ViewModeContextValue {
  const ctx = useContext(ViewModeContext);
  if (!ctx) {
    throw new Error('useViewMode must be used within a ViewModeProvider');
  }
  return ctx;
}
