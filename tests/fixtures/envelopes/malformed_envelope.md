# Code Review — Round 1

This envelope violates §4.1.1 — `status=APPROVED` paired with `next_action=RETURN_TO_WORKER` is forbidden by the schema's allOf clauses.

```json envelope
{
  "envelope_version": "1",
  "agent_id": "code-review-high",
  "agent_family": "claude-native",
  "agent_effort_tier": "high",
  "round": 1,
  "status": "APPROVED",
  "next_action": "RETURN_TO_WORKER",
  "feedback_to_forward": [
    {
      "severity": "significant",
      "description": "an inconsistent envelope — APPROVED status cannot pair with RETURN_TO_WORKER"
    }
  ],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```
