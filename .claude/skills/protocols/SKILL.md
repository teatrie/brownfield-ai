---
name: protocols
description: Forces the agent to explicitly refocus and realign with the repository's core protocols and coding standards to overcome context drift. Triggered by phrases like "protocols", "align", "refocus", or "refresh rules".
---

# 🛡️ Protocol & Standard Alignment

The user has invoked this skill because context drift may be occurring. You MUST immediately stop and refresh your understanding of this repository's strict operational rules before executing any further steps.

## Execution Steps

1. **Read Core Files**: You must silently read the contents of:
   - [CLAUDE.md](../../../CLAUDE.md)
   - [docs/coding_standards.md](../../../docs/coding_standards.md)
   - [docs/learnings.md](../../../docs/learnings.md)
2. **Read Relevant Sub-Protocols**: Based on the active task, you MUST also read the specific auxiliary protocol files located in [docs/](../../../docs) referenced by [CLAUDE.md](../../../CLAUDE.md) (e.g., [docs/planning_protocol.md](../../../docs/planning_protocol.md) for architecture/planning, [docs/verification_protocol.md](../../../docs/verification_protocol.md) before testing, [docs/delegation_protocol.md](../../../docs/delegation_protocol.md) when orchestrating subagents).
3. **Internalize**: Acknowledge the core directives, especially regarding JIT delegation, no hallucination/faking, and the TDD/CI verification loops.
4. **Acknowledge**: Respond to the user with a concise, 2-3 sentence confirmation that you have refreshed your context and are ready to proceed in strict compliance with the protocols. Do not print out the rules, just confirm readiness.
