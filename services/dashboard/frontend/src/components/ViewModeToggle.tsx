/**
 * Segmented control for switching between Markdown and Raw
 * artifact content display modes.
 */

import { useViewMode } from '../hooks/useViewMode';
import { InfoTip } from './InfoTip';

/**
 * Two-button segmented toggle for view mode selection.
 *
 * Uses setViewMode for explicit value setting rather than
 * blind toggling, since each button represents a specific mode.
 *
 * @returns A segmented control element.
 */
export function ViewModeToggle(): React.JSX.Element {
  const { viewMode, setViewMode } = useViewMode();

  return (
    <div className="view-mode-toggle-wrapper">
      <div className="view-mode-toggle">
        <button
          className={`view-mode-toggle__btn ${viewMode === 'markdown' ? 'view-mode-toggle__btn--active' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            setViewMode('markdown');
          }}
        >
          Markdown
        </button>
        <button
          className={`view-mode-toggle__btn ${viewMode === 'raw' ? 'view-mode-toggle__btn--active' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            setViewMode('raw');
          }}
        >
          Raw
        </button>
      </div>
      <InfoTip text="Controls the rendering format of artifact content. Markdown renders headings, tables, and lists. Raw shows the original text. Selection applies globally to all artifacts." />
    </div>
  );
}
