import { render, screen } from '@testing-library/react';
import { MarkdownContent } from '../../components/MarkdownContent';

describe('MarkdownContent', () => {
  it('renders markdown string as HTML with strong tag for bold', () => {
    render(<MarkdownContent content="**bold text**" />);

    const strong = screen.getByText('bold text');
    expect(strong.tagName).toBe('STRONG');
  });

  it('renders GFM tables', () => {
    const tableMarkdown = [
      '| Header 1 | Header 2 |',
      '| -------- | -------- |',
      '| Cell 1   | Cell 2   |',
    ].join('\n');

    const { container } = render(<MarkdownContent content={tableMarkdown} />);

    expect(container.querySelector('table')).toBeInTheDocument();
  });

  it('empty string input renders without throwing', () => {
    const { container } = render(<MarkdownContent content="" />);

    expect(container.querySelector('.markdown-body')).toBeInTheDocument();
  });

  it('applies additional className alongside markdown-body', () => {
    const { container } = render(
      <MarkdownContent content="hello" className="custom-cls" />,
    );

    const wrapper = container.querySelector('.markdown-body');
    expect(wrapper).toBeInTheDocument();
    expect(wrapper).toHaveClass('markdown-body');
    expect(wrapper).toHaveClass('custom-cls');
  });
});
