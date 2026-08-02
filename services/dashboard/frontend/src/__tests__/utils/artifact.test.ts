import type { ArtifactMetadata, ArtifactType } from '../../types';
import {
  MARKDOWN_ARTIFACT_TYPES,
  copyArtifactText,
  downloadArtifact,
} from '../../utils/artifact';

describe('MARKDOWN_ARTIFACT_TYPES', () => {
  it('contains exactly the 6 expected artifact types', () => {
    const expected: ArtifactType[] = [
      'plan_snapshot',
      'design_decision',
      'gate_verdict',
      'step_result',
      'wave_summary',
      'session_exit',
    ];

    expect(MARKDOWN_ARTIFACT_TYPES.size).toBe(6);
    for (const t of expected) {
      expect(MARKDOWN_ARTIFACT_TYPES.has(t)).toBe(true);
    }
  });

  it('is a Set instance with ReadonlySet type constraint', () => {
    // ReadonlySet omits .add() and .delete() from the type,
    // but the underlying Set still has them at runtime.
    // Freeze the set to verify immutability intent via Object.isFrozen
    // is NOT the case here -- ReadonlySet is a compile-time guard only.
    // We verify the type-level contract by confirming the set is a Set instance.
    expect(MARKDOWN_ARTIFACT_TYPES).toBeInstanceOf(Set);
  });
});

describe('downloadArtifact', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('constructs filename from metadata with colons replaced by hyphens', () => {
    const mockUrl = 'blob:test-url';
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => mockUrl),
      revokeObjectURL: vi.fn(),
    });

    const clickSpy = vi.fn();
    const anchorStub = { href: '', download: '', click: clickSpy };
    vi.spyOn(document, 'createElement').mockReturnValue(
      anchorStub as unknown as HTMLAnchorElement,
    );

    const metadata: ArtifactMetadata = {
      epic_id: 'EPIC-001',
      artifact_type: 'step_result',
      agent_model: 'test',
      wave: '',
      step: '',
      domain: '',
      verdict: '',
      timestamp: '2026-04-13T10:30:00Z',
      artifact_status: '',
      version: 0,
      attempt: '',
      sub_plan: '',
      parent_id: '',
      branches: '',
      epic_status: '',
      agent_role: '',
    };

    downloadArtifact('# Test content', metadata);

    expect(anchorStub.download).toBe('EPIC-001_step_result_2026-04-13T10-30-00Z.md');
    expect(anchorStub.href).toBe(mockUrl);
    expect(clickSpy).toHaveBeenCalledOnce();
  });

  it('calls URL.revokeObjectURL after 100ms delay', () => {
    vi.useFakeTimers();

    const mockUrl = 'blob:revoke-test';
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => mockUrl),
      revokeObjectURL,
    });

    vi.spyOn(document, 'createElement').mockReturnValue({
      href: '',
      download: '',
      click: vi.fn(),
    } as unknown as HTMLAnchorElement);

    const metadata: ArtifactMetadata = {
      epic_id: 'EPIC-002',
      artifact_type: 'plan_snapshot',
      agent_model: 'test',
      wave: '',
      step: '',
      domain: '',
      verdict: '',
      timestamp: '2026-04-13T12:00:00Z',
      artifact_status: '',
      version: 0,
      attempt: '',
      sub_plan: '',
      parent_id: '',
      branches: '',
      epic_status: '',
      agent_role: '',
    };

    downloadArtifact('content', metadata);

    expect(revokeObjectURL).not.toHaveBeenCalled();

    vi.advanceTimersByTime(100);

    expect(revokeObjectURL).toHaveBeenCalledWith(mockUrl);
  });
});

describe('copyArtifactText', () => {
  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      writable: true,
      configurable: true,
    });
  });

  it('returns false when navigator.clipboard is unavailable', async () => {
    // jsdom does not provide navigator.clipboard by default,
    // so the writeText call throws and the catch block returns false.
    const result = await copyArtifactText('test text');

    expect(result).toBe(false);
  });

  it('returns true when navigator.clipboard.writeText resolves', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    const result = await copyArtifactText('copied content');

    expect(result).toBe(true);
    expect(writeText).toHaveBeenCalledWith('copied content');
  });
});