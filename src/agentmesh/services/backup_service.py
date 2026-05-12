from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agentmesh.utils.yaml_io import read_yaml

SUPPORTED_METADATA_SCHEMAS = {
    "agentmesh.backup/v1",
    "agentmesh.restore/v1",
    "agentmesh.rollback-plan/v1",
}


def make_backup_id(history_id: str, backup_path: str) -> str:
    digest = hashlib.sha256(f"{history_id}\0{backup_path}".encode()).hexdigest()
    return f"bkp-{digest[:12]}"


def _history_file(agentmesh_home: Path) -> Path:
    return agentmesh_home / "state" / "sync-history.jsonl"


def _inside(root: Path, candidate: Path) -> bool:
    return root == candidate or root in candidate.parents


def _summary_from(entry: dict[str, Any]) -> dict[str, int]:
    summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    return {
        "actions": int(summary.get("actions", 0) or 0),
        "allowed": int(summary.get("allowed", 0) or 0),
        "blocked": int(summary.get("blocked", 0) or 0),
        "warnings": int(summary.get("warnings", 0) or 0),
    }


def _action_refs(entry: dict[str, Any]) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    actions = entry.get("actions") if isinstance(entry.get("actions"), list) else []
    for action in actions:
        if not isinstance(action, dict):
            continue
        refs.append(
            {
                "target": action.get("to"),
                "skill": action.get("skill"),
                "target_path": action.get("target_path"),
                "decision": action.get("decision"),
            }
        )
    return refs


def _metadata_info(backup_path: Path) -> dict[str, str | bool | None]:
    for name in ("backup.yaml", "restore.yaml", "plan.yaml"):
        candidate = backup_path / name
        if not candidate.exists():
            continue
        try:
            data = read_yaml(candidate)
        except Exception:
            return {
                "present": True,
                "schema": None,
                "path": str(candidate),
                "readable": False,
                "supported": False,
            }
        schema = data.get("schema") if isinstance(data, dict) else None
        supported = isinstance(schema, str) and schema in SUPPORTED_METADATA_SCHEMAS
        return {
            "present": True,
            "schema": schema if isinstance(schema, str) else None,
            "path": str(candidate),
            "readable": True,
            "supported": supported,
        }
    return {
        "present": False,
        "schema": None,
        "path": None,
        "readable": False,
        "supported": False,
    }


def _recoverability(
    agentmesh_home: Path,
    backup_path_raw: str,
    action_refs: list[dict[str, str | None]],
) -> tuple[dict[str, list[str] | str], dict[str, str | bool | None]]:
    backups_root = (agentmesh_home / "backups").resolve()
    candidate = Path(backup_path_raw).expanduser().resolve()
    if not _inside(backups_root, candidate):
        return (
            {
                "status": "unsafe_path",
                "reasons": ["backup path is outside <agentmesh_home>/backups"],
                "warnings": ["Unsafe backup path was not inspected."],
            },
            {"present": False, "schema": None, "path": None},
        )
    if not candidate.exists():
        return (
            {
                "status": "missing_path",
                "reasons": ["backup path does not exist on disk"],
                "warnings": ["Rollback must be blocked for this backup."],
            },
            {"present": False, "schema": None, "path": None},
        )
    metadata = _metadata_info(candidate)
    if not any(candidate.iterdir()):
        return (
            {
                "status": "empty_backup",
                "reasons": ["backup path is empty"],
                "warnings": ["Rollback must be blocked for this backup."],
            },
            metadata,
        )
    if metadata["present"] and metadata["readable"] and metadata["supported"]:
        return (
            {
                "status": "restorable",
                "reasons": ["backup metadata is present"],
                "warnings": [],
            },
            metadata,
        )
    if metadata["present"]:
        return (
            {
                "status": "partial",
                "reasons": ["backup metadata is unreadable or unsupported"],
                "warnings": ["Rollback must be blocked for this backup."],
            },
            metadata,
        )
    matched = False
    for ref in action_refs:
        target = ref.get("target")
        skill = ref.get("skill")
        if target and skill and (candidate / target / skill).exists():
            matched = True
            break
    status = "metadata_missing" if matched else "partial"
    return (
        {
            "status": status,
            "reasons": ["backup metadata is not present"],
            "warnings": ["Only conservative tree-level rollback can be planned from this backup."],
        },
        metadata,
    )


def _iter_history_entries(
    agentmesh_home: Path,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    path = _history_file(agentmesh_home)
    skipped = {
        "invalid_json_lines": 0,
        "unbacked_history_entries": 0,
        "non_applied_entries": 0,
        "non_sync_entries": 0,
    }
    warnings: list[str] = []
    if not path.exists():
        return [], skipped, warnings
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            skipped["invalid_json_lines"] += 1
            warnings.append(f"Skipped invalid JSON line {line_number} in sync-history.jsonl.")
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries, skipped, warnings


def list_backup_records(agentmesh_home: Path) -> dict[str, Any]:
    entries, skipped, warnings = _iter_history_entries(agentmesh_home)
    records: list[dict[str, Any]] = []
    counts = {
        "restorable": 0,
        "partial": 0,
        "metadata_missing": 0,
        "missing_path": 0,
        "empty_backup": 0,
        "unsafe_path": 0,
        "unknown": 0,
    }
    for entry in entries:
        if entry.get("operation") != "skills sync":
            skipped["non_sync_entries"] += 1
            continue
        if entry.get("status") != "applied":
            skipped["non_applied_entries"] += 1
            continue
        backup_raw = entry.get("backup")
        if not isinstance(backup_raw, str):
            skipped["unbacked_history_entries"] += 1
            continue
        history_id = str(entry.get("id") or f"legacy-{len(records) + 1}")
        action_refs = _action_refs(entry)
        recoverability, metadata = _recoverability(agentmesh_home, backup_raw, action_refs)
        status = str(recoverability["status"])
        counts[status if status in counts else "unknown"] += 1
        record = {
            "backup_id": make_backup_id(history_id, backup_raw),
            "history_id": history_id,
            "created_at": entry.get("timestamp"),
            "operation": entry.get("operation"),
            "status": entry.get("status"),
            "sync_mode": entry.get("sync_mode", "unknown"),
            "backup_path": backup_raw,
            "targets": entry.get("targets", []),
            "summary": _summary_from(entry),
            "action_refs": action_refs,
            "recoverability": recoverability,
            "metadata": metadata,
        }
        if status == "unsafe_path":
            # unsafe backup paths are excluded from list output
            continue
        records.append(record)
    safe_total = len(records)
    summary = {"total": safe_total, **counts, "skipped": skipped}
    return {
        "schema": "agentmesh.backup-list/v1",
        "command": "backup list",
        "status": "ok",
        "data": {"backups": records},
        "summary": summary,
        "warnings": warnings,
        "errors": [],
        "next_steps": [],
    }
