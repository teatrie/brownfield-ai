import { useCallback, useEffect, useRef, useState } from 'react';

/** Message received from the WebSocket server. */
interface WebSocketMessage {
  /** Event type identifier. */
  type: string;
  /** Optional epic identifier for targeted events. */
  epic_id?: string;
  /** Event payload data. */
  data?: unknown;
}

/**
 * Return value of the useWebSocket hook.
 */
interface UseWebSocketResult {
  /** The most recently received message, or null if none. */
  lastMessage: WebSocketMessage | null;
  /** Send a text message through the WebSocket connection. */
  sendMessage: (data: string) => void;
  /** Whether the WebSocket is currently connected. */
  isConnected: boolean;
}

/**
 * Hook for managing a WebSocket connection to the dashboard server.
 *
 * Establishes a connection to `ws://localhost:8484/ws`, automatically
 * reconnects on disconnection with exponential backoff, and exposes
 * the last received message and a send function.
 *
 * @param url - The WebSocket server URL. Defaults to `ws://localhost:8484/ws`.
 * @returns Connection state, last message, and send function.
 */
export function useWebSocket(url = 'ws://localhost:8484/ws'): UseWebSocketResult {
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const reconnectDelayRef = useRef(1000);

  const connect = useCallback(() => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      reconnectDelayRef.current = 1000;
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data as string) as WebSocketMessage;
        setLastMessage(parsed);
      } catch {
        /* ignore non-JSON messages */
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      wsRef.current = null;
      reconnectTimeoutRef.current = setTimeout(() => {
        reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 30000);
        connect();
      }, reconnectDelayRef.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [url]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { lastMessage, sendMessage, isConnected };
}
