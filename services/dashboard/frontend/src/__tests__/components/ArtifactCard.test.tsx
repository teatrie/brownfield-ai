import { render, screen, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ArtifactCard } from '../../components/ArtifactCard';
import { ViewModeProvider } from '../../hooks/useViewMode';
import type { Artifact, ArtifactMetadata } from '../../types';

function makeArtifact(overrides: Partial<ArtifactMetadata> = {}, content = '# Test content'): Artifact {
  return {
    id: 'test-artifact-1',
    document: content,
    metadata: {
      epic_id: 'EPIC-001',
      artifact_type: 'step_result',
      agent_model: 'test',
      wave: '1',
      step: '1',
      domain: 'test',
      verdict: 'GREEN',
      timestamp: '2026-04-14T10:30:00Z',
      artifact_status: 'active',
      version: 1,
      attempt: '1',
      sub_plan: '',
      parent_id: '',
      branches: '',
      epic_status: 'in_progress',
      agent_role: 'worker',
      ...overrides,
    },
  };
}

function renderCard(artifact: Artifact) {
  return render(
    <ViewModeProvider>
      <ArtifactCard artifact={artifact} />
    </ViewModeProvider>,
  );
}

describe('ArtifactCard', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      writable: true,
      configurable: true,
    });
  });

  it('(a) renders collapsed by default showing artifact type and timestamp', () => {
    const artifact = makeArtifact();
    renderCard(artifact);

    expect(screen.getByText('Step Result')).toBeInTheDocument();
    const contentDiv = document.querySelector('.artifact-card__content');
    expect(contentDiv).not.toHaveClass('artifact-card__content--expanded');
  });

  it('(b) clicking the article toggles expanded class', async () => {
    const user = userEvent.setup();
    const artifact = makeArtifact();
    renderCard(artifact);

    const article = document.querySelector('article.artifact-card')!;
    await user.click(article as HTMLElement);

    const contentDiv = document.querySelector('.artifact-card__content');
    expect(contentDiv).toHaveClass('artifact-card__content--expanded');
  });

  describe('(c) verdict CSS class mapping', () => {
    const cases: Array<[string, string]> = [
      ['GREEN', 'green'],
      ['PASS', 'green'],
      ['FAIL', 'fail'],
      ['RETRY', 'retry'],
      ['other', 'neutral'],
    ];

    for (const [verdict, expectedSuffix] of cases) {
      it(`verdict "${verdict}" applies class artifact-card__verdict--${expectedSuffix}`, () => {
        const artifact = makeArtifact({ verdict });
        const { container } = renderCard(artifact);
        const verdictEl = container.querySelector(`.artifact-card__verdict--${expectedSuffix}`);
        expect(verdictEl).toBeInTheDocument();
      });
    }
  });

  describe('(d) copy button triggers clipboard and reverts after 2s', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('copy button shows Copied! then reverts after 2000ms', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText },
        writable: true,
        configurable: true,
      });

      const artifact = makeArtifact();
      renderCard(artifact);

      const article = document.querySelector('article.artifact-card')!;
      fireEvent.click(article as HTMLElement);

      const copyBtn = screen.getByText('Copy');
      await act(async () => {
        fireEvent.click(copyBtn);
        // flush the clipboard promise
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(screen.getByText('Copied!')).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(2000);
      });

      expect(screen.getByText('Copy')).toBeInTheDocument();
    });
  });

  it('(e) download button triggers download', () => {
    const mockUrl = 'blob:test-url';
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => mockUrl),
      revokeObjectURL: vi.fn(),
    });

    const clickSpy = vi.fn();
    const anchorStub = { href: '', download: '', click: clickSpy };
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'a') return anchorStub as unknown as HTMLElement;
      return originalCreateElement(tag);
    });

    const artifact = makeArtifact();
    renderCard(artifact);

    const article = document.querySelector('article.artifact-card')!;
    fireEvent.click(article as HTMLElement);

    const downloadBtn = screen.getByText('Download');
    fireEvent.click(downloadBtn);

    expect(clickSpy).toHaveBeenCalled();
  });

  it('(f) markdown view mode renders MarkdownContent for markdown artifact types', async () => {
    const user = userEvent.setup();
    const artifact = makeArtifact({ artifact_type: 'step_result' });
    const { container } = renderCard(artifact);

    const article = document.querySelector('article.artifact-card')!;
    await user.click(article as HTMLElement);

    expect(container.querySelector('.markdown-body')).toBeInTheDocument();
  });

  it('(g) raw view mode renders pre block with artifact-card__text class', async () => {
    const user = userEvent.setup();
    localStorage.setItem('viewMode', 'raw');

    const artifact = makeArtifact({ artifact_type: 'step_result' });
    const { container } = renderCard(artifact);

    const article = document.querySelector('article.artifact-card')!;
    await user.click(article as HTMLElement);

    const pre = container.querySelector('pre.artifact-card__text');
    expect(pre).toBeInTheDocument();
  });
});
