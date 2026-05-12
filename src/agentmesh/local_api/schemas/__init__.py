"""Command schemas for the AgentMesh Web 工作台.

Each schema describes one `agentmesh` CLI command: its title, description,
the parameters the UI should collect, and enough metadata for the front-end
to assemble a valid command string without server round-trips.

The schemas live here (not in CLI source) because they are a contract between
the CLI and the UI. The CLI itself stays canonical; these schemas are a
machine-readable projection for the form renderer.

Public API:
- ``CommandSchema`` / ``CommandParam`` dataclasses
- ``get_schema(command_id)`` — lookup by id
- ``list_schemas()`` — return all registered schemas (sorted by id)
- ``assemble_command(schema, values)`` — return a CLI command string from values
- ``validate_values(schema, values)`` — return a list of validation errors

Design constraints:
- Schemas are declarative and pure (no side effects at import time).
- The CLI prefix is always ``am`` for the assembled string (matches the
  workstation convention; command_service also accepts ``agentmesh``).
- Registry is intentionally auto-added by the server from the caller, not
  embedded in schemas, so one schema works for every registry path.
"""

from __future__ import annotations

# Re-export registry helpers at package root for convenience.
from agentmesh.local_api.schemas.registry import (  # noqa: E402
    get_schema,
    list_schemas,
    register_schema,
)
from agentmesh.local_api.schemas.types import (
    CommandParam,
    CommandSchema,
    SchemaValidationError,
    assemble_command,
    validate_values,
)

__all__ = [
    "CommandParam",
    "CommandSchema",
    "SchemaValidationError",
    "assemble_command",
    "get_schema",
    "list_schemas",
    "register_schema",
    "validate_values",
]
