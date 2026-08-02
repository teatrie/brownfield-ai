"""Content sanitization for execution ledger artifacts.

Applies secret/PII redaction and head+tail truncation to artifacts
whose body may carry sensitive content (per ``SANITIZED_ARTIFACT_TYPES``).
"""

from __future__ import annotations

from brownfield_ai.ledger.artifacts.constants import (
    REDACTION_PATTERNS,
    SANITIZED_ARTIFACT_TYPES,
    TRUNCATION_HEAD,
    TRUNCATION_TAIL,
    TRUNCATION_THRESHOLD,
)


def sanitize_content(content: str, artifact_type: str) -> str:
    """Sanitize content for storage, applying redaction (and step_result truncation).

    For artifact types listed in ``SANITIZED_ARTIFACT_TYPES``: redact
    secrets and PII via byte-equivalent substitution that preserves any
    surrounding JSON structure. Head+tail truncation is applied
    **only** to ``step_result`` bodies — the dissent-lifecycle artifact
    types carry strictly structured JSON (per the appendix in
    ``docs/verification_protocol.md``) and a naive byte-slice
    truncation would corrupt the JSON, making the artifact unparseable
    by ``json.loads``. The dissent-lifecycle bodies are bounded by
    their schemas (a few hundred to a few thousand characters in
    typical use), so truncation is unnecessary; redaction is sufficient
    to protect operator emails and bridge identifiers.

    Args:
        content: The raw content string.
        artifact_type: The artifact type being checkpointed.

    Returns:
        str: The sanitized content string.
    """
    if artifact_type not in SANITIZED_ARTIFACT_TYPES:
        return content

    sanitized = content
    for pattern in REDACTION_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)

    if artifact_type == "step_result" and len(sanitized) > TRUNCATION_THRESHOLD:
        middle_len = len(sanitized) - TRUNCATION_HEAD - TRUNCATION_TAIL
        sanitized = sanitized[:TRUNCATION_HEAD] + f"\n... [TRUNCATED {middle_len} chars] ...\n" + sanitized[-TRUNCATION_TAIL:]

    return sanitized
