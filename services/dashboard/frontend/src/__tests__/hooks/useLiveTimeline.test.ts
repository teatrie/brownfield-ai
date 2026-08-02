import { renderHook, act } from '@testing-library/react';
import { useLiveTimeline } from '../../hooks/useLiveTimeline';
import { createMockWebSocket } from '../helpers/mockWebSocket';
import type { MockWSInstance } from '../helpers/mockWebSocket';
import type { ArtifactMetadata } from '../../types';

/** All created mock WebSocket instances during a test. */
let wsInstances: MockWSInstance[];

/** The mock WebSocket constructor with static constants. */
let MockWebSocket: ReturnType<typeof vi.fn> & {
  CONNECTING: number;
  OPEN: number;
  CLOSING: number;
  CLOSED: number;
};

/**
 * Build minimal artifact metadata for tests.
 */
function makeMetadata(epicId: string): ArtifactMetadata {
  return {
    epic_id: epicId,
    artifact_type: 'step_result',
    agent_model: 'test',
    wave: '1',
    step: '1',
    domain: 'test',
    verdict: 'GREEN',
    timestamp: '2026-04-14T00:00:00Z',
    artifact_status: 'active',
    version: 1,
    attempt: '1',
    sub_plan: '',
    parent_id: '',
    branches: '',
    epic_status: 'in_progress',
    agent_role: 'worker',
  };
}

describe('useLiveTimeline', () => {
  beforeEach(() => {
    vi.useFakeTimers();

    const result = createMockWebSocket();
    wsInstances = result.wsInstances;
    MockWebSocket = result.MockWebSocket;

    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('sends subscribe message when connected with an epicId', () => {
    renderHook(() => useLiveTimeline('EPIC-1'));

    const ws = wsInstances[0]!;

    // Simulate connection open
    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    expect(ws.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'subscribe', epic_id: 'EPIC-1' }),
    );
  });

  it('accumulates artifact_new messages matching the subscribed epicId', () => {
    const { result } = renderHook(() => useLiveTimeline('EPIC-1'));
    const ws = wsInstances[0]!;

    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    // Send two matching artifact_new messages
    act(() => {
      ws.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'artifact_new',
            epic_id: 'EPIC-1',
            data: {
              id: 'art-1',
              document: 'First artifact',
              metadata: makeMetadata('EPIC-1'),
            },
          }),
        }),
      );
    });

    act(() => {
      ws.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'artifact_new',
            epic_id: 'EPIC-1',
            data: {
              id: 'art-2',
              document: 'Second artifact',
              metadata: makeMetadata('EPIC-1'),
            },
          }),
        }),
      );
    });

    expect(result.current.newArtifacts).toHaveLength(2);
    // Newest first
    expect(result.current.newArtifacts[0]!.id).toBe('art-2');
    expect(result.current.newArtifacts[1]!.id).toBe('art-1');
  });

  it('ignores messages for different epicIds', () => {
    const { result } = renderHook(() => useLiveTimeline('EPIC-1'));
    const ws = wsInstances[0]!;

    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    act(() => {
      ws.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'artifact_new',
            epic_id: 'EPIC-2',
            data: {
              id: 'art-other',
              document: 'Other epic',
              metadata: makeMetadata('EPIC-2'),
            },
          }),
        }),
      );
    });

    expect(result.current.newArtifacts).toHaveLength(0);
  });

  it('clearNew resets accumulated artifacts array', () => {
    const { result } = renderHook(() => useLiveTimeline('EPIC-1'));
    const ws = wsInstances[0]!;

    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    act(() => {
      ws.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'artifact_new',
            epic_id: 'EPIC-1',
            data: {
              id: 'art-1',
              document: 'Artifact',
              metadata: makeMetadata('EPIC-1'),
            },
          }),
        }),
      );
    });

    expect(result.current.newArtifacts).toHaveLength(1);

    act(() => {
      result.current.clearNew();
    });

    expect(result.current.newArtifacts).toHaveLength(0);
  });

  it('cleanup on unmount: WebSocket is closed', () => {
    const { unmount } = renderHook(() => useLiveTimeline('EPIC-1'));
    const ws = wsInstances[0]!;

    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    unmount();

    expect(ws.close).toHaveBeenCalled();
  });

  it('useLiveTimeline(null) does not send subscribe message', () => {
    renderHook(() => useLiveTimeline(null));
    const ws = wsInstances[0]!;

    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    expect(ws.send).not.toHaveBeenCalled();
  });

  it('ignores non-artifact_new message types', () => {
    const { result } = renderHook(() => useLiveTimeline('EPIC-1'));
    const ws = wsInstances[0]!;

    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    // Send a message with type 'epic_change' instead of 'artifact_new'
    act(() => {
      ws.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'epic_change',
            epic_id: 'EPIC-1',
            data: { status: 'completed', last_updated_at: '2026-04-14T12:00:00Z' },
          }),
        }),
      );
    });

    expect(result.current.newArtifacts).toHaveLength(0);
  });

  it('epic ID change resets newArtifacts to empty array', () => {
    const { result, rerender } = renderHook(
      ({ epicId }: { epicId: string | null }) => useLiveTimeline(epicId),
      { initialProps: { epicId: 'EPIC-1' as string | null } },
    );

    const ws = wsInstances[0]!;

    act(() => {
      ws.readyState = WebSocket.OPEN;
      ws.onopen?.(new Event('open'));
    });

    // Add an artifact for EPIC-1
    act(() => {
      ws.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'artifact_new',
            epic_id: 'EPIC-1',
            data: {
              id: 'art-1',
              document: 'Artifact',
              metadata: makeMetadata('EPIC-1'),
            },
          }),
        }),
      );
    });

    expect(result.current.newArtifacts).toHaveLength(1);

    // Change epic ID
    rerender({ epicId: 'EPIC-2' });

    expect(result.current.newArtifacts).toHaveLength(0);
  });
});
