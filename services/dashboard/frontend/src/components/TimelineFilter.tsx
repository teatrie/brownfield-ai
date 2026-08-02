/**
 * Filter controls for the artifact timeline view.
 *
 * Provides pill toggles for artifact types, text inputs for wave
 * and domain filtering, and a dropdown for verdict selection.
 * All filters are optional -- empty values mean no filter applied.
 */

import { useCallback } from 'react';
import type { ArtifactType } from '../types';

/** All recognized artifact types for pill toggle display. */
const ARTIFACT_TYPES: ArtifactType[] = [
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

/** Verdict options for the dropdown filter. */
const VERDICT_OPTIONS: string[] = ['', 'GREEN', 'FAIL', 'RETRY'];

/** Active filter state managed by the parent component. */
export interface TimelineFilters {
  /** Currently selected artifact type, or empty for all. */
  artifactType: string;
  /** Wave metadata filter value. */
  wave: string;
  /** Domain metadata filter value. */
  domain: string;
  /** Verdict metadata filter value. */
  verdict: string;
}

/** Props for the TimelineFilter component. */
interface TimelineFilterProps {
  /** Current filter state. */
  filters: TimelineFilters;
  /** Callback invoked when any filter value changes. */
  onFilterChange: (filters: TimelineFilters) => void;
}

/**
 * Format an artifact type slug for display.
 *
 * Replaces underscores with spaces and converts to title case.
 *
 * @param artifactType - Raw type string (e.g. "step_result").
 * @returns Formatted display string (e.g. "Step Result").
 */
function formatType(artifactType: string): string {
  return artifactType
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Filter bar for the artifact timeline.
 *
 * Renders pill toggles for each artifact type, text inputs for
 * wave and domain, and a dropdown for verdict. Changes are
 * propagated to the parent via the onFilterChange callback.
 *
 * @param props - Component props with filters and change handler.
 * @returns A filter controls element.
 */
export function TimelineFilter({ filters, onFilterChange }: TimelineFilterProps): React.JSX.Element {
  /** Handle clicking an artifact type pill toggle. */
  const handleTypeClick = useCallback(
    (type: string) => {
      onFilterChange({
        ...filters,
        artifactType: filters.artifactType === type ? '' : type,
      });
    },
    [filters, onFilterChange],
  );

  /** Handle wave input change. */
  const handleWaveChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onFilterChange({ ...filters, wave: e.target.value });
    },
    [filters, onFilterChange],
  );

  /** Handle domain input change. */
  const handleDomainChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onFilterChange({ ...filters, domain: e.target.value });
    },
    [filters, onFilterChange],
  );

  /** Handle verdict dropdown change. */
  const handleVerdictChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onFilterChange({ ...filters, verdict: e.target.value });
    },
    [filters, onFilterChange],
  );

  return (
    <div className="timeline-filter">
      <div className="timeline-filter__types">
        {ARTIFACT_TYPES.map((type) => (
          <button
            key={type}
            className={`filter-pill ${filters.artifactType === type ? 'filter-pill--active' : ''}`}
            onClick={() => handleTypeClick(type)}
          >
            {formatType(type)}
          </button>
        ))}
      </div>
      <div className="timeline-filter__fields">
        <input
          type="text"
          className="filter-input"
          placeholder="Wave"
          value={filters.wave}
          onChange={handleWaveChange}
        />
        <input
          type="text"
          className="filter-input"
          placeholder="Domain"
          value={filters.domain}
          onChange={handleDomainChange}
        />
        <select
          className="filter-dropdown"
          value={filters.verdict}
          onChange={handleVerdictChange}
        >
          {VERDICT_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt === '' ? 'All Verdicts' : opt}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
