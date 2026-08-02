"""Orchestrator helpers for the Reviewer Output Envelope migration.

This package hosts the deterministic-routing primitives used by the
orchestrator and the reviewer-aggregation skills. See
``docs/reviewer_envelope.md`` for the canonical reference document.

Wave 1 ships :mod:`scripts.orchestrator.envelope_parser` only. The
forward-referenced ``envelope_merge`` and ``envelope_circuit_breaker``
modules land in W4 per the epic plan
(``tmp/plan-reviewer-output-envelope.md`` §6.5).
"""
