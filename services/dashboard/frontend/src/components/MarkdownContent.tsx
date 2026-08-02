/**
 * Rendered Markdown display component for artifact content.
 *
 * Wraps ReactMarkdown with GFM support for tables, checkboxes,
 * strikethrough, and autolinks. No syntax highlighting in v1.
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const REMARK_PLUGINS = [remarkGfm];

/** Props for the MarkdownContent component. */
interface MarkdownContentProps {
  /** Raw Markdown string to render. */
  content: string;
  /** Optional additional CSS class name. */
  className?: string;
}

/**
 * Render a Markdown string as formatted HTML.
 *
 * Uses remark-gfm for GitHub Flavored Markdown support.
 * HTML pass-through is intentionally disabled (no rehype-raw)
 * as a security measure against XSS.
 *
 * @param props - Component props with content and optional class.
 * @returns A rendered Markdown element.
 */
export function MarkdownContent({ content, className }: MarkdownContentProps): React.JSX.Element {
  return (
    <div className={`markdown-body ${className ?? ''}`}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>{content}</ReactMarkdown>
    </div>
  );
}
