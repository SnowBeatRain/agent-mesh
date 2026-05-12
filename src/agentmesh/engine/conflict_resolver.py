"""Conflict classification primitives shared across the engine and services.

Historically this module also exported a `classify_conflict(source, target)`
helper that took two raw file paths and returned a coarse result. It has been
removed in Phase 0 cleanup: the real sync/diff flow goes through
`agentmesh.engine.diff_engine.diff_skill` which works on skill directories,
honours AgentMesh-generated metadata, and has richer test coverage
(`test_full_diff_conflicts`, `test_conflict_policy`, `test_safe_apply`, ...).
"""

from dataclasses import dataclass
from enum import IntEnum


class ConflictLevel(IntEnum):
    IDENTICAL = 0
    METADATA_ONLY = 1
    CONTENT_CHANGED = 2
    STRUCTURE_CHANGED = 3
    MANUAL_REVIEW = 4
    SECURITY_BLOCK = 5


@dataclass(frozen=True)
class ConflictResult:
    level: ConflictLevel
    name: str
    summary: str
    changes: list[dict] | None = None
