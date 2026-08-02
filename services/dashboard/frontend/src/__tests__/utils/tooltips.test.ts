import type { ArtifactType } from '../../types';
import { ARTIFACT_TYPE_TIPS, SECTION_TIPS } from '../../utils/tooltips';

/** Exhaustive list of all ArtifactType union members. */
const ALL_ARTIFACT_TYPES: ArtifactType[] = [
  'plan_snapshot',
  'design_decision',
  'gate_verdict',
  'step_result',
  'wave_summary',
  'requirement_map',
  'pr_created',
  'pr_merged',
  'todo_linked',
  'ci_resolution',
  'pr_changes_required',
  'session_exit',
];

describe('ARTIFACT_TYPE_TIPS', () => {
  it('has a tooltip for every ArtifactType and no extra keys', () => {
    const tipKeys = Object.keys(ARTIFACT_TYPE_TIPS);

    // Every ArtifactType has a corresponding tip
    for (const artifactType of ALL_ARTIFACT_TYPES) {
      expect(tipKeys).toContain(artifactType);
      expect(typeof ARTIFACT_TYPE_TIPS[artifactType]).toBe('string');
      expect(ARTIFACT_TYPE_TIPS[artifactType].length).toBeGreaterThan(0);
    }

    // No extra keys beyond the 12 ArtifactType members
    expect(tipKeys).toHaveLength(ALL_ARTIFACT_TYPES.length);
  });
});

describe('SECTION_TIPS', () => {
  it('is a non-empty record with string values', () => {
    const entries = Object.entries(SECTION_TIPS);

    expect(entries.length).toBeGreaterThan(0);

    for (const [key, value] of entries) {
      expect(typeof key).toBe('string');
      expect(typeof value).toBe('string');
      expect(value.length).toBeGreaterThan(0);
    }
  });
});