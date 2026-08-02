/**
 * WebSocket hook for real-time artifact timeline updates.
 *
 * Subscribes to a specific epic's artifact stream and accumulates
 * newly detected artifacts for the parent page to prepend to
 * the timeline.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Artifact } from '../types';
import { useWebSocket } from './useWebSocket';

/** Return value of the useLiveTimeline hook. */
interface UseLiveTimelineResult {
  /** Newly received artifacts since mount, newest first. */
  newArtifacts: Artifact[];
  /** Clear the accumulated new artifacts buffer. */
  clearNew: () => void;
}

/**
 * Subscribe to live artifact updates for a given epic via WebSocket.
 *
 * Sends a subscribe message on mount and listens for ``artifact_new``
 * events. Accumulates new artifacts in an array that the parent
 * component can prepend to its timeline state.
 *
 * @param epicId - The epic identifier to subscribe to. Pass ``null`` to disable.
 * @returns Object containing the new artifacts array and a clear function.
 */
export function useLiveTimeline(epicId: string | null): UseLiveTimelineResult {
  const { lastMessage, sendMessage, isConnected } = useWebSocket();
  const [newArtifacts, setNewArtifacts] = useState<Artifact[]>([]);
  const subscribedRef = useRef<string | null>(null);

  // Subscribe when connected and epicId changes
  useEffect(() => {
    if (!isConnected || !epicId) {
      return;
    }
    if (subscribedRef.current !== epicId) {
      sendMessage(JSON.stringify({ type: 'subscribe', epic_id: epicId }));
      subscribedRef.current = epicId;
    }
  }, [isConnected, epicId, sendMessage]);

  // Reset state when epicId changes
  useEffect(() => {
    setNewArtifacts([]);
    subscribedRef.current = null;
  }, [epicId]);

  // Process incoming messages
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'artifact_new') {
      return;
    }
    if (epicId && lastMessage.epic_id === epicId && lastMessage.data) {
      const data = lastMessage.data as {
        id: string;
        document: string;
        metadata: Artifact['metadata'];
      };
      const artifact: Artifact = {
        id: data.id,
        document: data.document,
        metadata: data.metadata,
      };
      setNewArtifacts((prev) => [artifact, ...prev]);
    }
  }, [lastMessage, epicId]);

  /** Clear the accumulated new artifacts buffer. */
  const clearNew = useCallback(() => {
    setNewArtifacts([]);
  }, []);

  return { newArtifacts, clearNew };
}
