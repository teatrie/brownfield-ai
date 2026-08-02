# Code Review — Round 1

The agent attempted an envelope but emitted the closer line directly
after the opener with no body line at all. The two adjacent fences
must be classified as `malformed_envelope_fence`, not `envelope absent`
(TODO-0152).

```json envelope
```
