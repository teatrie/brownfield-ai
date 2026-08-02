/**
 * Full artifact detail view panel.
 *
 * Displays the complete document content without truncation,
 * a full metadata table covering all 16 fields, and syntax-
 * highlighted code blocks. Provides a back/close button for
 * returning to the timeline view.
 */

import { useState, useEffect } from 'react';
import type { Artifact, ArtifactMetadata } from '../types';
import { copyArtifactText, downloadArtifact, MARKDOWN_ARTIFACT_TYPES } from '../utils/artifact';
import { useViewMode } from '../hooks/useViewMode';
import { ARTIFACT_TYPE_TIPS } from '../utils/tooltips';
import { InfoTip } from './InfoTip';
import { MarkdownContent } from './MarkdownContent';
import { ViewModeToggle } from './ViewModeToggle';

/** Props for the ArtifactDetail component. */
interface ArtifactDetailProps {
  /** The artifact to display in full. */
  artifact: Artifact;
  /** Callback invoked when the user closes the detail view. */
  onClose: () => void;
}

/**
 * Format an artifact type slug for display.
 *
 * Replaces underscores with spaces and converts to title case.
 *
 * @param artifactType - Raw type string (e.g. "step_result").
 * @returns Formatted display string (e.g. "Step Result").
 */
function formatArtifactType(artifactType: string): string {
  return artifactType
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Format an ISO-8601 timestamp into a full readable string.
 *
 * @param timestamp - ISO-8601 date string.
 * @returns Locale-formatted full date and time.
 */
function formatTimestamp(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return timestamp;
  }
}

/** All metadata keys to display in the detail table. */
const METADATA_KEYS: Array<keyof ArtifactMetadata> = [
  'epic_id',
  'artifact_type',
  'agent_model',
  'wave',
  'step',
  'domain',
  'verdict',
  'timestamp',
  'artifact_status',
  'version',
  'attempt',
  'sub_plan',
  'parent_id',
  'branches',
  'epic_status',
  'agent_role',
];

/**
 * Format a metadata key for display as a table label.
 *
 * Replaces underscores with spaces and converts to title case.
 *
 * @param key - Raw metadata key string.
 * @returns Formatted label string.
 */
function formatKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Full artifact detail panel with metadata table and content.
 *
 * Renders a header with artifact type badge and close button,
 * a two-column metadata table showing all 16 fields, and the
 * full document content with syntax-highlighted code blocks
 * using ``<pre><code>`` elements.
 *
 * @param props - Component props with artifact and close handler.
 * @returns A detail view element.
 */
export function ArtifactDetail({ artifact, onClose }: ArtifactDetailProps): React.JSX.Element {
  const { metadata, document: content } = artifact;
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const { viewMode } = useViewMode();

  return (
    <div className="artifact-detail">
      <div className="artifact-detail__header">
        <button className="artifact-detail__back" onClick={onClose}>
          Back
        </button>
        <span className="artifact-card__type">
          {formatArtifactType(metadata.artifact_type)}
          {ARTIFACT_TYPE_TIPS[metadata.artifact_type] && (
            <InfoTip text={ARTIFACT_TYPE_TIPS[metadata.artifact_type]} />
          )}
        </span>
        {metadata.verdict && (
          <span className={`artifact-card__verdict artifact-card__verdict--${metadata.verdict.toUpperCase() === 'GREEN' ? 'green' : metadata.verdict.toUpperCase() === 'FAIL' ? 'fail' : metadata.verdict.toUpperCase() === 'RETRY' ? 'retry' : 'neutral'}`}>
            {metadata.verdict.toUpperCase()}
          </span>
        )}
        <div className="artifact-actions">
          <button
            className={`artifact-actions__btn ${copied ? 'artifact-actions__btn--copied' : ''}`}
            onClick={() => {
              copyArtifactText(content).then((ok) => {
                if (ok) setCopied(true);
              });
            }}
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <button
            className="artifact-actions__btn"
            onClick={() => downloadArtifact(content, metadata)}
          >
            Download
          </button>
        </div>
        <span className="artifact-detail__id mono">{artifact.id}</span>
      </div>

      <div className="artifact-detail__metadata">
        <h3 className="artifact-detail__section-title">Metadata</h3>
        <table className="artifact-detail__table">
          <tbody>
            {METADATA_KEYS.map((key) => {
              const value = metadata[key];
              const displayValue =
                key === 'timestamp' && typeof value === 'string'
                  ? formatTimestamp(value)
                  : String(value ?? '');
              return (
                <tr key={key}>
                  <td className="artifact-detail__key mono">{formatKey(key)}</td>
                  <td className="artifact-detail__value">{displayValue}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="artifact-detail__content">
        <div className="artifact-detail__content-header">
          <h3 className="artifact-detail__section-title">Content</h3>
          <ViewModeToggle />
        </div>
        {viewMode === 'markdown' && MARKDOWN_ARTIFACT_TYPES.has(metadata.artifact_type) ? (
          <MarkdownContent content={content} />
        ) : (
          <pre className="artifact-detail__code">
            <code>{content}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
