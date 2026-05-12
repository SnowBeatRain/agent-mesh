"""In-memory registry of all CommandSchemas.

Schemas are registered at import time from the per-command modules
(``core.py``, ``skills.py`` etc.). Keeping them declarative here means the
HTTP endpoints and the tests can both read the same source of truth without
touching the CLI.
"""

from __future__ import annotations

from agentmesh.local_api.schemas.types import CommandSchema

_REGISTRY: dict[str, CommandSchema] = {}


def register_schema(schema: CommandSchema) -> None:
    """Register a schema. Duplicate ids replace the previous registration.

    We allow replacement (rather than raising) to keep the import story
    simple in tests that re-import the package. Production imports are
    single-shot so this is effectively idempotent.
    """
    _REGISTRY[schema.id] = schema


def get_schema(command_id: str) -> CommandSchema | None:
    return _REGISTRY.get(command_id)


def list_schemas() -> list[CommandSchema]:
    return [_REGISTRY[key] for key in sorted(_REGISTRY)]


def clear_registry() -> None:
    """Used by tests to isolate registration state; do not call in production."""
    _REGISTRY.clear()


# Import sub-modules so side-effect registrations execute. Keep the imports
# at the bottom to avoid circular import issues during module load.
from agentmesh.local_api.schemas import agents as _agents  # noqa: E402,F401
from agentmesh.local_api.schemas import audit as _audit  # noqa: E402,F401
from agentmesh.local_api.schemas import core as _core  # noqa: E402,F401
from agentmesh.local_api.schemas import package as _package  # noqa: E402,F401
from agentmesh.local_api.schemas import rollback as _rollback  # noqa: E402,F401
from agentmesh.local_api.schemas import runtime as _runtime  # noqa: E402,F401
from agentmesh.local_api.schemas import skills as _skills  # noqa: E402,F401
