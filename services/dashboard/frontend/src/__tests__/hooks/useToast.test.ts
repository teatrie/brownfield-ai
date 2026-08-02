import { renderHook, act } from '@testing-library/react';
import { useToast } from '../../hooks/useToast';

describe('useToast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('showToast sets toast message in state', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.showToast('Hello');
    });

    expect(result.current.toast).toBe('Hello');
  });

  it('toast auto-clears after 3000ms timeout', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.showToast('Temporary');
    });

    expect(result.current.toast).toBe('Temporary');

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current.toast).toBeNull();
  });

  it('rapid successive calls: only second message is visible, clears after one 3000ms timeout', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.showToast('first');
    });

    act(() => {
      result.current.showToast('second');
    });

    expect(result.current.toast).toBe('second');

    // Advance by 3000ms - the second timer should clear
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current.toast).toBeNull();
  });
});
