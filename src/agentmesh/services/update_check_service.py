from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmesh.services.registry_service import list_registry_skills
from agentmesh.utils.yaml_io import read_yaml

UPDATE_CHECK_SCHEMA = "agentmesh.update-check/v1"

SOURCE_IDENTITY_KEYS = (
    "kind",
    "source_agent",
    "source_path",
    "package_path",
    "package_sha256",
    "imported_at",
    "original_hash",
)


def _manifest_source(skill_dir: Path) -> dict[str, Any] | None:
    manifest_path = skill_dir / "agentmesh.asset.yaml"
    if not manifest_path.exists():
        return None
    source = read_yaml(manifest_path).get("source")
    return source if isinstance(source, dict) else None


def _source_identity(source: dict[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for key in SOURCE_IDENTITY_KEYS:
        if key in source:
            identity[key] = source[key]
    identity.setdefault("kind", str(source.get("type", "unknown")))
    return identity


def build_update_check(agentmesh_home: Path) -> dict[str, Any]:
    """Build a read-only local update preflight report.

    M7 deliberately does not access networks, download packages, or inspect tokens. It only reports
    whether each registry skill has source identity that can feed a future update flow.
    """

    items: list[dict[str, Any]] = []
    summary = {"total": 0, "candidate": 0, "unknown": 0, "skipped": 0}
    for skill_dir in list_registry_skills(agentmesh_home):
        summary["total"] += 1
        source = _manifest_source(skill_dir)
        if source is None:
            summary["skipped"] += 1
            items.append(
                {
                    "name": skill_dir.name,
                    "status": "skipped",
                    "reason": "no-source",
                    "source": None,
                    "remote_checked": False,
                }
            )
            continue

        identity = _source_identity(source)
        if identity.get("kind") == "agentmesh-package":
            summary["unknown"] += 1
            items.append(
                {
                    "name": skill_dir.name,
                    "status": "unknown",
                    "reason": "network-disabled",
                    "source": identity,
                    "remote_checked": False,
                }
            )
            continue

        summary["skipped"] += 1
        items.append(
            {
                "name": skill_dir.name,
                "status": "skipped",
                "reason": "unsupported-source",
                "source": identity,
                "remote_checked": False,
            }
        )
    return {
        "schema": UPDATE_CHECK_SCHEMA,
        "network": "disabled",
        "summary": summary,
        "skills": items,
    }
