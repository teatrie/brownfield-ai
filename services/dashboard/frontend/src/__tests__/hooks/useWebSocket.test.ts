import { renderHook, act } from '@testing-library/react';
import { useWebSocket } from '../../hooks/useWebSocket';
import { simulateOpen, simulateMessage } from '../helpers/mockWebSocket';
import type { MockWSInstance } from '../helpers/mockWebSocket';

/** All created mock WebSocket instances during a test. */
let wsInstances: MockWSInstance[];

/** The mock WebSocket constructor with static constants. */
let MockWebSocket: ReturnType<typeof vi.fn> & {
  CONNECTING: number;
  OPEN: number;
  CLOSING: number;
  CLOSED: number;
};

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    wsInstances = [];

    // Must be a `function`, not an arrow: the hook calls `new WebSocket(url)`,
    // and Vitest 4 refuses to construct a mock whose implementation is not
    // constructible.
    const factory = vi.fn().mockImplementation(function (url: string) {
      const instance: MockWSInstance = {
        onopen: null,
        onmessage: null,
        onclose: null,
        onerror: null,
        send: vi.fn(),
        close: vi.fn(),
        readyState: WebSocket.CONNECTING,
        url,
      };
      // Trigger onclose when close() is called, matching real WebSocket
      // behavior. Closes over `instance` lexically rather than relying on a
      // `this`-bound function: under Vitest 4 the mock type no longer resolves
      // `.bind()` to a single call signature (TS2349).
      instance.close.mockImplementation(() => {
        if (instance.onclose) {
          instance.readyState = WebSocket.CLOSED;
          instance.onclose(new CloseEvent('close'));
        }
      });
      wsInstances.push(instance);
      return instance;
    });

    // Attach the static constants from the real WebSocket
    Object.assign(factory, {
      CONNECTING: 0,
      OPEN: 1,
      CLOSING: 2,
      CLOSED: 3,
    });
    MockWebSocket = factory as typeof MockWebSocket;

    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('sets isConnected true on open, false on close', () => {
    const { result } = renderHook(() => useWebSocket('ws://test'));

    const ws = wsInstances[0]!;
    expect(result.current.isConnected).toBe(false);

    act(() => {
      simulateOpen(ws);
    });

    expect(result.current.isConnected).toBe(true);

    act(() => {
      // Directly invoke onclose to avoid the close() -> onclose -> reconnect -> close() loop
      ws.readyState = WebSocket.CLOSED;
      ws.onclose?.(new CloseEvent('close'));
    });

    expect(result.current.isConnected).toBe(false);
  });

  it('parses JSON messages and updates lastMessage', () => {
    const { result } = renderHook(() => useWebSocket('ws://test'));
    const ws = wsInstances[0]!;

    act(() => {
      simulateOpen(ws);
    });

    act(() => {
      simulateMessage(ws, JSON.stringify({ type: 'test_event', data: 42 }));
    });

    expect(result.current.lastMessage).toEqual({
      type: 'test_event',
      data: 42,
    });
  });

  it('ignores non-JSON messages without throwing', () => {
    const { result } = renderHook(() => useWebSocket('ws://test'));
    const ws = wsInstances[0]!;

    act(() => {
      simulateOpen(ws);
    });

    // Send a valid message first
    act(() => {
      simulateMessage(ws, JSON.stringify({ type: 'first' }));
    });

    expect(result.current.lastMessage).toEqual({ type: 'first' });

    // Send non-JSON - should not throw or update lastMessage
    act(() => {
      simulateMessage(ws, 'not valid json {{');
    });

    // lastMessage stays as the previous valid message
    expect(result.current.lastMessage).toEqual({ type: 'first' });
  });

  it('reconnects with exponential backoff on close', () => {
    const { result } = renderHook(() => useWebSocket('ws://test'));
    const ws = wsInstances[0]!;

    expect(wsInstances).toHaveLength(1);

    // Simulate close (triggers reconnect timer)
    act(() => {
      ws.readyState = WebSocket.CLOSED;
      ws.onclose?.(new CloseEvent('close'));
    });

    expect(result.current.isConnected).toBe(false);

    // Advance by initial delay (1000ms) - should create new WebSocket
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(wsInstances).toHaveLength(2);
  });

  it('backoff caps at 30000ms', () => {
    renderHook(() => useWebSocket('ws://test'));

    // Simulate multiple close/reconnect cycles to reach the cap.
    // Delays: 1000, 2000, 4000, 8000, 16000, 30000 (capped)
    for (let i = 0; i < 6; i++) {
      const ws = wsInstances[wsInstances.length - 1]!;
      act(() => {
        ws.readyState = WebSocket.CLOSED;
        ws.onclose?.(new CloseEvent('close'));
      });
      const expectedDelay = Math.min(1000 * Math.pow(2, i), 30000);
      act(() => {
        vi.advanceTimersByTime(expectedDelay);
      });
    }

    // After 6 cycles, the last close should reconnect at 30000ms cap.
    // Close the 7th connection and verify the delay is still 30000ms
    const wsBefore = wsInstances.length;
    const ws7 = wsInstances[wsInstances.length - 1]!;
    act(() => {
      ws7.readyState = WebSocket.CLOSED;
      ws7.onclose?.(new CloseEvent('close'));
    });

    // Advance less than 30000ms - no new connection
    act(() => {
      vi.advanceTimersByTime(29999);
    });
    expect(wsInstances).toHaveLength(wsBefore);

    // Advance remaining 1ms - new connection
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(wsInstances).toHaveLength(wsBefore + 1);
  });

  it('backoff resets to 1000ms after successful reconnect open', () => {
    renderHook(() => useWebSocket('ws://test'));

    // First close -> reconnect at 1000ms
    const ws1 = wsInstances[0]!;
    act(() => {
      ws1.readyState = WebSocket.CLOSED;
      ws1.onclose?.(new CloseEvent('close'));
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // Second close -> reconnect at 2000ms
    const ws2 = wsInstances[1]!;
    act(() => {
      ws2.readyState = WebSocket.CLOSED;
      ws2.onclose?.(new CloseEvent('close'));
    });
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    // Now simulate successful open - delay should reset
    const ws3 = wsInstances[2]!;
    act(() => {
      simulateOpen(ws3);
    });

    // Close again - should reconnect at 1000ms (reset), not 4000ms
    const countBefore = wsInstances.length;
    act(() => {
      ws3.readyState = WebSocket.CLOSED;
      ws3.onclose?.(new CloseEvent('close'));
    });

    // At 1000ms a new connection should appear
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(wsInstances).toHaveLength(countBefore + 1);
  });

  it('sendMessage is no-op when WebSocket is not in OPEN state', () => {
    const { result } = renderHook(() => useWebSocket('ws://test'));
    const ws = wsInstances[0]!;

    // WebSocket is CONNECTING, not OPEN
    expect(ws.readyState).toBe(WebSocket.CONNECTING);

    act(() => {
      result.current.sendMessage('hello');
    });

    expect(ws.send).not.toHaveBeenCalled();
  });

  it('onerror triggers close and subsequent reconnect', () => {
    renderHook(() => useWebSocket('ws://test'));
    const ws = wsInstances[0]!;

    expect(wsInstances).toHaveLength(1);

    // Simulate error — source code at useWebSocket.ts line 69: ws.onerror = () => { ws.close(); }
    // The mock's close() triggers onclose which triggers reconnect
    act(() => {
      ws.onerror?.(new Event('error'));
    });

    // After the close triggered by onerror, the reconnect timer should fire
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // A new WebSocket instance should have been created via reconnect
    expect(wsInstances).toHaveLength(2);
  });
});
