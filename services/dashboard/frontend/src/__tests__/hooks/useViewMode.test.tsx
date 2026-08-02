import { renderHook, act } from '@testing-library/react';
import { ViewModeProvider, useViewMode } from '../../hooks/useViewMode';
import type { ReactNode } from 'react';

/** Wrapper that provides the ViewModeProvider context. */
function wrapper({ children }: { children: ReactNode }) {
  return <ViewModeProvider>{children}</ViewModeProvider>;
}

describe('useViewMode', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('ViewModeProvider provides default markdown mode', () => {
    const { result } = renderHook(() => useViewMode(), { wrapper });

    expect(result.current.viewMode).toBe('markdown');
  });

  it('toggleViewMode switches between markdown and raw', () => {
    const { result } = renderHook(() => useViewMode(), { wrapper });

    act(() => {
      result.current.toggleViewMode();
    });

    expect(result.current.viewMode).toBe('raw');

    act(() => {
      result.current.toggleViewMode();
    });

    expect(result.current.viewMode).toBe('markdown');
  });

  it('setViewMode explicitly sets mode to raw', () => {
    const { result } = renderHook(() => useViewMode(), { wrapper });

    act(() => {
      result.current.setViewMode('raw');
    });

    expect(result.current.viewMode).toBe('raw');
  });

  it('useViewMode throws Error when called outside provider', () => {
    // Suppress React error boundary console output; restored by afterEach.
    vi.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      renderHook(() => useViewMode());
    }).toThrow('useViewMode must be used within a ViewModeProvider');
  });

  it('mode change writes to localStorage', () => {
    const { result } = renderHook(() => useViewMode(), { wrapper });

    act(() => {
      result.current.setViewMode('raw');
    });

    expect(localStorage.getItem('viewMode')).toBe('raw');
  });
});
