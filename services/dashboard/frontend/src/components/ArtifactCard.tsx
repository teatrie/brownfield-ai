/**
 * Artifact display card for the execution ledger timeline.
 *
 * Shows artifact type, verdict, timestamp, metadata, and an
 * expandable content preview. Clicking toggles between a
 * collapsed 3-line preview and the full artifact content.
 */

import { useState, useEffect } from 'react';
import type { Artifact } from '../types';
import { copyArtifactText, downloadArtifact, MARKDOWN_ARTIFACT_TYPES } from '../utils/artifact';
import { useViewMode } from '../hooks/useViewMode';
import { ARTIFACT_TYPE_TIPS } from '../utils/tooltips';
import { InfoTip } from './InfoTip';
import { MarkdownContent } from './MarkdownContent';

/** Props for the ArtifactCard component. */
interface ArtifactCardProps {
  /** The artifact to display. */
  artifact: Artifact;
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
 * Format an ISO-8601 timestamp into a compact display string.
 *
 * @param timestamp - ISO-8601 date string.
 * @returns Locale-formatted date and time, or the raw string on failure.
 */
function formatTimestamp(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return timestamp;
  }
}

/**
 * Determine the CSS modifier class for a verdict value.
 *
 * @param verdict - Verdict string (e.g. "GREEN", "FAIL", "RETRY").
 * @returns CSS class suffix for verdict coloring.
 */
function getVerdictClass(verdict: string): string {
  const upper = verdict.toUpperCase();
  if (upper === 'GREEN' || upper === 'PASS') return 'green';
  if (upper === 'FAIL') return 'fail';
  if (upper === 'RETRY') return 'retry';
  return 'neutral';
}

/**
 * Expandable card displaying an execution ledger artifact.
 *
 * Shows the artifact type as a badge, verdict indicator,
 * timestamp in monospace, wave/domain/step metadata inline,
 * and a content preview that expands on click.
 *
 * @param props - Component props containing the artifact.
 * @returns A styled article element.
 */
export function ArtifactCard({ artifact }: ArtifactCardProps): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const { metadata, document: content } = artifact;

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const { viewMode } = useViewMode();

  const hasVerdict = metadata.verdict && metadata.verdict !== '';

  return (
    <article className="artifact-card" onClick={() => setExpanded((prev) => !prev)}>
      <div className="artifact-card__header">
        <span className="artifact-card__type">
          {formatArtifactType(metadata.artifact_type)}
          {ARTIFACT_TYPE_TIPS[metadata.artifact_type] && (
            <InfoTip text={ARTIFACT_TYPE_TIPS[metadata.artifact_type]} />
          )}
        </span>
        {hasVerdict && (
          <span className={`artifact-card__verdict artifact-card__verdict--${getVerdictClass(metadata.verdict)}`}>
            {metadata.verdict.toUpperCase()}
          </span>
        )}
        <span className="artifact-card__timestamp mono">
          {formatTimestamp(metadata.timestamp)}
        </span>
        <div className="artifact-card__meta">
          {metadata.wave && (
            <span className="artifact-card__meta-tag">W{metadata.wave}</span>
          )}
          {metadata.domain && (
            <span className="artifact-card__meta-tag">{metadata.domain}</span>
          )}
          {metadata.step && (
            <span className="artifact-card__meta-tag">S{metadata.step}</span>
          )}
        </div>
      </div>
      {content && (
        <div
          className={`artifact-card__content ${expanded ? 'artifact-card__content--expanded' : ''}`}
        >
          {expanded && content && (
            <div className="artifact-actions" onClick={(e) => e.stopPropagation()}>
              <button
                className={`artifact-actions__btn ${copied ? 'artifact-actions__btn--copied' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  copyArtifactText(content).then((ok) => {
                    if (ok) setCopied(true);
                  });
                }}
              >
                {copied ? 'Copied!' : 'Copy'}
              </button>
              <button
                className="artifact-actions__btn"
                onClick={(e) => {
                  e.stopPropagation();
                  downloadArtifact(content, metadata);
                }}
              >
                Download
              </button>
            </div>
          )}
          {expanded && viewMode === 'markdown' && MARKDOWN_ARTIFACT_TYPES.has(metadata.artifact_type) ? (
            <MarkdownContent content={content} />
          ) : (
            <pre className="artifact-card__text">{content}</pre>
          )}
        </div>
      )}
    </article>
  );
}
