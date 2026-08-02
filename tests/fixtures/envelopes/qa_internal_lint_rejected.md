# QA Lint Gate — Round 1

I ran `task lint:staged` against the staged tree.

- ruff format / check: 1 violation reported.
- mypy: clean.
- python-sql wildcard scan: clean.
- markdownlint / yamllint / jsonlint: clean.

The single ruff F401 violation is unresolved and blocks the lint gate.
The fix is mechanical (drop the unused import), but the gate is RED until
the worker addresses it.

Verdict: REJECTED. Returning to worker for the lint-gate fix.

```json envelope
{
  "envelope_version": "1",
  "agent_id": "qa-lint",
  "agent_family": "qa-internal",
  "agent_effort_tier": "medium",
  "round": 1,
  "status": "REJECTED",
  "next_action": "RETURN_TO_WORKER",
  "feedback_to_forward": [
    {
      "severity": "significant",
      "file_path": "scripts/orchestrator/envelope_parser.py",
      "line_range": "27",
      "description": "ruff F401 — `from dataclasses import asdict` is imported but never used. Drop the import or move it under a TYPE_CHECKING guard if it is annotation-only.",
      "suggested_fix": "Remove the unused import on line 27.",
      "rule_id": "F401",
      "blocking": true
    }
  ],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```
