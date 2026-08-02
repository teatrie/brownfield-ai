import type { Artifact } from '../../types';
import { groupArtifactsByDate, formatDateHeader } from '../../utils/date';

/**
 * Factory for minimal Artifact objects used in date utility tests.
 *
 * @param timestamp - ISO-8601 timestamp string, or empty string if omitted.
 * @returns A valid Artifact with the given timestamp in metadata.
 */
const makeArtifact = (timestamp?: string): Artifact => ({
  id: 'test-id',
  document: 'test content',
  metadata: {
    epic_id: 'TEST-001',
    artifact_type: 'step_result',
    agent_model: 'test',
    wave: '',
    step: '',
    domain: '',
    verdict: '',
    timestamp: timestamp ?? '',
    artifact_status: '',
    version: 0,
    attempt: '',
    sub_plan: '',
    parent_id: '',
    branches: '',
    epic_status: '',
    agent_role: '',
  },
});

describe('groupArtifactsByDate', () => {
  it('groups artifacts by YYYY-MM-DD extracted from timestamp', () => {
    const artifacts = [
      makeArtifact('2026-04-13T10:00:00Z'),
      makeArtifact('2026-04-13T14:30:00Z'),
      makeArtifact('2026-04-12T08:00:00Z'),
    ];

    const groups = groupArtifactsByDate(artifacts);

    expect(groups.size).toBe(2);
    expect(groups.get('2026-04-13')).toHaveLength(2);
    expect(groups.get('2026-04-12')).toHaveLength(1);
  });

  it('returns "unknown" key when timestamp is undefined', () => {
    const artifact = makeArtifact();
    // Force timestamp to undefined to exercise the ?? 'unknown' fallback.
    // The type says string, but runtime data may have gaps.
    (artifact.metadata as unknown as Record<string, unknown>).timestamp = undefined;

    const groups = groupArtifactsByDate([artifact]);

    expect(groups.has('unknown')).toBe(true);
    expect(groups.get('unknown')).toHaveLength(1);
  });

  it('preserves insertion order within each group', () => {
    const first = makeArtifact('2026-04-13T09:00:00Z');
    first.id = 'first';
    const second = makeArtifact('2026-04-13T10:00:00Z');
    second.id = 'second';
    const third = makeArtifact('2026-04-13T11:00:00Z');
    third.id = 'third';

    const groups = groupArtifactsByDate([first, second, third]);
    const items = groups.get('2026-04-13')!;

    expect(items[0]!.id).toBe('first');
    expect(items[1]!.id).toBe('second');
    expect(items[2]!.id).toBe('third');
  });

  it('returns empty Map for empty input array', () => {
    const groups = groupArtifactsByDate([]);

    expect(groups.size).toBe(0);
  });

  it('uses full string as key when timestamp lacks "T" separator', () => {
    const artifacts = [makeArtifact('2026-04-13')];

    const groups = groupArtifactsByDate(artifacts);

    // split('T')[0] on a string without 'T' returns the whole string
    expect(groups.has('2026-04-13')).toBe(true);
    expect(groups.get('2026-04-13')).toHaveLength(1);
  });
});

describe('formatDateHeader', () => {
  it('formats valid YYYY-MM-DD into a locale string containing the year', () => {
    const result = formatDateHeader('2026-04-13');

    expect(result).toContain('2026');
  });

  it('returns "Invalid Date" for unparseable date string', () => {
    const result = formatDateHeader('not-a-date');

    // new Date('not-a-dateT00:00:00') produces Invalid Date.
    // In V8/jsdom toLocaleDateString() does not throw; it returns
    // the string "Invalid Date" directly.
    expect(result).toBe('Invalid Date');
  });

  it('returns "Invalid Date" when given "unknown" as input', () => {
    const result = formatDateHeader('unknown');

    // Same behavior: new Date('unknownT00:00:00') is Invalid Date,
    // and toLocaleDateString() returns "Invalid Date" without throwing.
    expect(result).toBe('Invalid Date');
  });
});