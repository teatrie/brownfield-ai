# Code Review — Round 1

For reference, the schema example block looks like this:

```json
{
  "envelope_version": "1",
  "agent_id": "EXAMPLE-FROM-PROSE",
  "agent_family": "claude-native",
  "agent_effort_tier": "high",
  "round": 999,
  "status": "REJECTED",
  "next_action": "RETURN_TO_WORKER",
  "feedback_to_forward": [
    {"severity": "critical", "description": "this is a fake example in prose, not the real envelope"}
  ],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```

Note: the block above is illustrative only and MUST NOT be promoted by the parser as the envelope. My actual envelope follows the discriminated `json envelope` info-string convention below.

```json envelope
{
  "envelope_version": "1",
  "agent_id": "code-review-high",
  "agent_family": "claude-native",
  "agent_effort_tier": "high",
  "round": 1,
  "status": "APPROVED",
  "next_action": "APPROVE",
  "feedback_to_forward": [],
  "recommended_next_tier": null,
  "halt_trigger": null
}
```
