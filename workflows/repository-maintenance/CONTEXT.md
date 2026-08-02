# repository-maintenance

Continuous workflow optimization domain. This domain focuses on the upkeep of our AI development tools, testing scaffolding, and architectural routing.

## Available Skills

- [claude-review](skills/claude-review/SKILL.md): Reviews the .claude folder (skills and agents) for consistency, correctness, and redundancy against repository protocols.
- [docs-review](skills/docs-review/SKILL.md): Audit, update, and clean repository documentation to extract learnings, remove redundancy, and keep CLAUDE.md strictly minimal.
- [skill-creator](skills/third-party/skill-creator/SKILL.md): Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, update or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better triggering accuracy.
- [status-sync](skills/status-sync/SKILL.md): "Review project state, pause, and resume epics across machines by managing remote branches and the Execution Ledger. Triggered via `/status`, `/status pause`, or `/status resume <branch>`."
- [workflow-management](skills/workflow-management/SKILL.md): Orchestrates the creation of new workspace workflow domains and the integration of new skills into those workflows. Use when you need to define a new architectural domain, manage an existing domain's structure, or correctly initialize scaffolding when integrating skills using the skill-creator.

## Available Prompts

- [repos-research.prompt.md](prompts/repos-research.prompt.md): Plan a deep research epic for upstream services to produce repo-guides, .claude/rules/, and .github/instructions/ documentation artifacts.
- [security-verification.prompt.md](prompts/security-verification.prompt.md): Audit Claude Code security settings across all three layers (global, project-shared, project-local), run runtime verification checks, and advise on gaps using reference settings as a baseline.
