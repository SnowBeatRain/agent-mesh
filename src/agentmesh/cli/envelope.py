from __future__ import annotations

from typing import Any, Literal

EnvelopeStatus = Literal["ok", "planned", "applied", "blocked", "error"]
VALID_STATUSES = {"ok", "planned", "applied", "blocked", "error"}


def build_envelope(
    schema: str,
    command: str,
    status: EnvelopeStatus | str,
    data: dict[str, Any],
    summary: dict[str, Any] | None = None,
    *,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> dict[str, Any]:
    """Build a normalized AgentMesh CLI JSON envelope."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid envelope status: {status}")
    return {
        "schema": schema,
        "command": command,
        "status": status,
        "data": data,
        "summary": summary or {},
        "warnings": list(warnings or []),
        "errors": list(errors or []),
        "next_steps": list(next_steps or []),
    }
