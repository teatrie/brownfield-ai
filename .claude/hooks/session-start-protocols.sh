#!/usr/bin/env bash
set -euo pipefail

echo 'Context was just compacted. A SessionStart hook, not the user, injected the protocols skill below (source: .claude/skills/protocols/SKILL.md under the project root; its relative links resolve from that file). Run its Read Core Files, Read Relevant Sub-Protocols and Internalize steps silently, with no message to the user. If a task is in progress, resume it instead of the Acknowledge step, unless the latest user message redirects it. Otherwise, run the Acknowledge step.'
cat "$CLAUDE_PROJECT_DIR/.claude/skills/protocols/SKILL.md"
