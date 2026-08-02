import { VALID_TRANSITIONS } from '../types';

/** Terminal states that appear as targets but not as source keys. */
const TERMINAL_STATES = ['completed', 'abandoned'];

describe('VALID_TRANSITIONS', () => {
  it('every defined status has at least one outbound transition', () => {
    for (const [, targets] of Object.entries(VALID_TRANSITIONS)) {
      expect(targets.length).toBeGreaterThan(0);
      expect(Array.isArray(targets)).toBe(true);
    }
  });

  it('completed and abandoned are terminal (not keys in the map)', () => {
    const sourceStatuses = Object.keys(VALID_TRANSITIONS);

    for (const terminal of TERMINAL_STATES) {
      expect(sourceStatuses).not.toContain(terminal);
    }
  });

  it('no transition target references an undefined source except terminals', () => {
    const sourceStatuses = new Set(Object.keys(VALID_TRANSITIONS));
    const terminalSet = new Set(TERMINAL_STATES);

    for (const [, targets] of Object.entries(VALID_TRANSITIONS)) {
      for (const target of targets) {
        const isKnown = sourceStatuses.has(target) || terminalSet.has(target);
        expect(isKnown).toBe(true);
      }
    }
  });

  it('backlog has exactly ["pending", "approved"]', () => {
    expect(VALID_TRANSITIONS.backlog).toEqual(['pending', 'approved']);
  });
});