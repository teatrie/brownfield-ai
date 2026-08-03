/**
 * Shared WebSocket mock helpers for Vitest hook tests.
 *
 * Provides a reusable factory and event-simulation utilities so that
 * individual test files don't need to duplicate the MockWSInstance
 * scaffolding.
 */

/**
 * Minimal mock WebSocket instance with controllable event handlers.
 */
export interface MockWSInstance {
  onopen: ((ev: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
  send: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  readyState: number;
  url: string;
}

/**
 * Mock WebSocket constructor type that includes the static readyState
 * constants expected by code under test.
 */
export type MockWebSocketConstructor = ReturnType<typeof vi.fn> & {
  CONNECTING: number;
  OPEN: number;
  CLOSING: number;
  CLOSED: number;
};

/**
 * Create a fresh MockWebSocket factory and accompanying instance registry.
 *
 * Each call returns a new `wsInstances` array and a `MockWebSocket`
 * constructor mock.  The factory builds `MockWSInstance` objects with a
 * simple `vi.fn()` close stub, then pushes each instance onto the shared
 * array so tests can address individual connections by index.
 *
 * @returns An object containing the instance registry and the typed
 *   constructor mock ready to be passed to `vi.stubGlobal('WebSocket', …)`.
 */
export function createMockWebSocket(): {
  wsInstances: MockWSInstance[];
  MockWebSocket: MockWebSocketConstructor;
} {
  const wsInstances: MockWSInstance[] = [];

  // Must be a `function`, not an arrow: consumers call `new WebSocket(url)`,
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
    wsInstances.push(instance);
    return instance;
  });

  Object.assign(factory, {
    CONNECTING: 0,
    OPEN: 1,
    CLOSING: 2,
    CLOSED: 3,
  });

  return { wsInstances, MockWebSocket: factory as MockWebSocketConstructor };
}

/**
 * Simulate the WebSocket open event on a mock instance.
 *
 * Sets `readyState` to `OPEN` and fires the `onopen` handler so that
 * hooks that gate logic on the open event behave as they would with a
 * real connection.
 *
 * @param ws - The mock instance whose open event should be triggered.
 */
export function simulateOpen(ws: MockWSInstance): void {
  ws.readyState = WebSocket.OPEN;
  ws.onopen?.(new Event('open'));
}

/**
 * Simulate a WebSocket message event with the given string data.
 *
 * @param ws   - The mock instance that should receive the message.
 * @param data - The raw string payload (typically a JSON string).
 */
export function simulateMessage(ws: MockWSInstance, data: string): void {
  ws.onmessage?.(new MessageEvent('message', { data }));
}
