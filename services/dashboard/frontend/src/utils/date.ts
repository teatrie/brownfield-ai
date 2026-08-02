/**
 * Shared date utilities for artifact timeline grouping and display.
 */

import type { Artifact } from '../types';

/**
 * Group artifacts by their date (YYYY-MM-DD) for timeline display.
 *
 * @param artifacts - Array of artifacts sorted by timestamp.
 * @returns Map of date strings to arrays of artifacts.
 */
export function groupArtifactsByDate(artifacts: Artifact[]): Map<string, Artifact[]> {
  const groups = new Map<string, Artifact[]>();
  for (const artifact of artifacts) {
    const dateKey = artifact.metadata.timestamp?.split('T')[0] ?? 'unknown';
    const existing = groups.get(dateKey);
    if (existing) {
      existing.push(artifact);
    } else {
      groups.set(dateKey, [artifact]);
    }
  }
  return groups;
}

/**
 * Format a date key string into a readable group header.
 *
 * @param dateKey - Date string in YYYY-MM-DD format.
 * @returns Formatted date header (e.g. "Apr 3, 2026").
 */
export function formatDateHeader(dateKey: string): string {
  try {
    return new Date(dateKey + 'T00:00:00').toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return dateKey;
  }
}
