import { render, screen, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ArtifactDetail } from '../../components/ArtifactDetail';
import { ViewModeProvider } from '../../hooks/useViewMode';
import type { Artifact, ArtifactMetadata } from '../../types';

function makeArtifact(overrides: Partial<ArtifactMetadata> = {}, content = '# Detail content'): Artifact {
  return {
    id: 'test-artifact-detail-1',
    document: content,
    metadata: {
      epic_id: 'EPIC-001',
      artifact_type: 'step_result',
      agent_model: 'test-model',
      wave: '1',
      step: '2',
      domain: 'backend',
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

function renderDetail(artifact: Artifact, onClose = vi.fn()) {
  return render(
    <ViewModeProvider>
      <ArtifactDetail artifact={artifact} onClose={onClose} />
    </ViewModeProvider>,
  );
}

describe('ArtifactDetail', () => {
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

  it('(a) renders 16-field metadata table', () => {
    const artifact = makeArtifact();
    const { container } = renderDetail(artifact);

    const rows = container.querySelectorAll('.artifact-detail__table tr');
    expect(rows).toHaveLength(16);
  });

  it('(b) back button calls onClose', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const artifact = makeArtifact();
    const { container } = renderDetail(artifact, onClose);

    const backBtn = container.querySelector('.artifact-detail__back')!;
    await user.click(backBtn as HTMLElement);

    expect(onClose).toHaveBeenCalledOnce();
  });

  it('(c) copy button shows Copied! after successful clipboard write', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    vi.useFakeTimers();

    const artifact = makeArtifact();
    renderDetail(artifact);

    await act(async () => {
      fireEvent.click(screen.getByText('Copy'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('Copied!')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getByText('Copy')).toBeInTheDocument();

    vi.useRealTimers();
  });

  it('(d) download button triggers blob creation', () => {
    const mockUrl = 'blob:detail-test-url';
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
    renderDetail(artifact);

    fireEvent.click(screen.getByText('Download'));

    expect(clickSpy).toHaveBeenCalled();
  });

  it('(e) ViewModeToggle is embedded with Markdown and Raw buttons', () => {
    const artifact = makeArtifact();
    renderDetail(artifact);

    expect(screen.getByRole('button', { name: 'Markdown' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Raw' })).toBeInTheDocument();
  });

  it('(f) formatKey produces expected output for table cell labels', () => {
    const artifact = makeArtifact();
    const { container } = renderDetail(artifact);

    const keyCells = Array.from(container.querySelectorAll('.artifact-detail__key'));
    const cellTexts = keyCells.map((el) => el.textContent);

    expect(cellTexts).toContain('Epic Id');
    expect(cellTexts).toContain('Artifact Type');
  });

  it('(g) invalid timestamp renders as "Invalid Date" from toLocaleString', () => {
    // new Date('') produces an Invalid Date object; toLocaleString returns "Invalid Date"
    // rather than throwing, so the component renders that string directly.
    const artifact = makeArtifact({ timestamp: '' });
    const { container } = renderDetail(artifact);

    // Find the timestamp row by its key label
    const rows = Array.from(container.querySelectorAll('.artifact-detail__table tr'));
    const timestampRow = rows.find((row) =>
      row.querySelector('.artifact-detail__key')?.textContent === 'Timestamp',
    )!;
    const valueCell = timestampRow.querySelector('.artifact-detail__value');
    expect(valueCell?.textContent).toBe('Invalid Date');
  });
});
