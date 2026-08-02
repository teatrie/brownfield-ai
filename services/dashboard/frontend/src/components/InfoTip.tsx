/**
 * Reusable info tooltip icon.
 *
 * Renders a small circled "i" that displays a tooltip on hover
 * via CSS ``::after`` pseudo-element. Placed outside any
 * ``overflow: hidden`` containers to avoid clipping.
 */

/** Props for the InfoTip component. */
interface InfoTipProps {
  /** Tooltip text displayed on hover. */
  text: string;
}

/**
 * Small info icon with a CSS-driven hover tooltip.
 *
 * @param props - Component props with tooltip text.
 * @returns An inline info icon element.
 */
export function InfoTip({ text }: InfoTipProps): React.JSX.Element {
  return (
    <span className="info-tip" data-tooltip={text}>i</span>
  );
}
