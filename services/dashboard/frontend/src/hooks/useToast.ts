/**
 * Auto-dismissing toast notification hook.
 *
 * Provides a simple toast state and a trigger function that
 * automatically clears the message after a fixed delay.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

/** Return value of the useToast hook. */
interface UseToastResult {
  /** The current toast message, or null when no toast is visible. */
  toast: string | null;
  /** Display a toast message that auto-dismisses after 3 seconds. */
  showToast: (message: string) => void;
}

/**
 * Hook for displaying an auto-dismissing toast notification.
 *
 * Each call to `showToast` resets the dismiss timer so that
 * rapid successive calls do not stack or leave stale messages.
 *
 * @returns Toast state and trigger function.
 */
export function useToast(): UseToastResult {
  const [toast, setToast] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const showToast = useCallback((message: string) => {
    if (timerRef.current !== undefined) {
      clearTimeout(timerRef.current);
    }
    setToast(message);
    timerRef.current = setTimeout(() => {
      setToast(null);
      timerRef.current = undefined;
    }, 3000);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current !== undefined) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  return { toast, showToast };
}
