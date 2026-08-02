"""Artifact ID generation and metadata construction.

Provides ``generate_id`` for composite document IDs, ``validate_artifact_type``
for enum validation, and ``build_metadata`` for flat metadata dictionaries.
"""

from __future__ import annotations

import sys
from typing import Any

from brownfield_ai.ledger.artifacts.constants import VALID_ARTIFACT_TYPES


def generate_id(fields: dict[str, str]) -> str:
    """Generate a composite document ID for lexicographic chronological sort.

    All field values are sanitized by replacing ``|`` with ``-`` to prevent
    delimiter injection. Fields are ordered as:
    ``epic_id|timestamp|artifact_type|agent_model|wave|step``.

    Args:
        fields: Dictionary with keys ``epic_id``, ``timestamp``,
            ``artifact_type``, ``agent_model``, ``wave``, ``step``.

    Returns:
        str: Pipe-delimited composite ID.
    """
    ordered_keys = [
        "epic_id",
        "timestamp",
        "artifact_type",
        "agent_model",
        "wave",
        "step",
    ]
    sanitized = [str(fields.get(k, "")).replace("|", "-") for k in ordered_keys]
    return "|".join(sanitized)


def validate_artifact_type(artifact_type: str) -> None:
    """Validate that *artifact_type* is in the allowed enum.

    Args:
        artifact_type: The artifact type string to validate.

    Raises:
        SystemExit: If the type is not recognized.
    """
    if artifact_type not in VALID_ARTIFACT_TYPES:
        print(f"Invalid artifact_type '{artifact_type}'. Must be one of: {sorted(VALID_ARTIFACT_TYPES)}")
        sys.exit(1)


def build_metadata(fields: dict[str, Any]) -> dict[str, Any]:
    """Build a flat metadata dictionary for ChromaDB storage.

    Empty optional fields use empty string ``""`` -- never ``None``.
    Ensures all 17 required metadata keys are present.

    Args:
        fields: Dictionary containing metadata field values. Expected keys:
            ``epic_id``, ``artifact_type``, ``wave``, ``domain``, ``step``,
            ``agent_role``, ``agent_model``, ``verdict``, ``timestamp``,
            ``version`` (int), ``parent_id``, ``epic_status``,
            ``artifact_status``, ``sub_plan``, ``sub_plans``, ``attempt``,
            ``branches``. ``sub_plan`` is a singular child-artifact
            scoping tag; ``sub_plans`` is a pipe-delimited epic-level
            master index read by ``parse_sub_plans`` in ralph.

    Returns:
        dict: Flat metadata dictionary with all 17 fields.
    """
    keys = [
        "epic_id",
        "artifact_type",
        "wave",
        "domain",
        "step",
        "agent_role",
        "agent_model",
        "verdict",
        "timestamp",
        "version",
        "parent_id",
        "epic_status",
        "artifact_status",
        "sub_plan",
        "sub_plans",
        "attempt",
        "branches",
    ]
    meta: dict[str, Any] = {k: fields.get(k, "") for k in keys}
    if meta["version"] == "":
        meta["version"] = 0
    return meta
