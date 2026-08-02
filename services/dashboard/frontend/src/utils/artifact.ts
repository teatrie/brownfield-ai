import type { ArtifactMetadata, ArtifactType } from '../types';

/** Artifact types whose content is prose/markdown and should respect the view mode toggle. */
export const MARKDOWN_ARTIFACT_TYPES: ReadonlySet<ArtifactType> = new Set([
  'plan_snapshot',
  'design_decision',
  'gate_verdict',
  'step_result',
  'wave_summary',
  'session_exit',
]);

/**
 * Copy artifact text to the clipboard.
 *
 * @param text - Raw text content to copy.
 * @returns True on success, false on rejection.
 */
export async function copyArtifactText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * Download artifact content as a Markdown file.
 *
 * Builds a filesystem-safe filename from metadata, creates a Blob,
 * and triggers a download via a hidden anchor element.
 *
 * @param content - Raw document body.
 * @param metadata - Artifact metadata for filename construction.
 */
export function downloadArtifact(content: string, metadata: ArtifactMetadata): void {
  const safeTimestamp = metadata.timestamp.replace(/:/g, '-');
  const filename = `${metadata.epic_id}_${metadata.artifact_type}_${safeTimestamp}.md`;
  const blob = new Blob([content], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 100);
}
