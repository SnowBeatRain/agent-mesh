from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentmesh.config import loader
from agentmesh.engine.diff_engine import target_skill_path
from agentmesh.paths.guard import PathGuard, PathViolation
from agentmesh.services.backup_service import list_backup_records
from agentmesh.services.sync_service import LOCK_FILE, _read_link_lock, _tree_hash
from agentmesh.utils.yaml_io import read_yaml, write_yaml


class RollbackApplyBlocked(RuntimeError):
    """Raised when rollback apply cannot safely proceed."""


APPLY_DECISIONS = {"restore_tree", "restore_managed_symlink_to_tree"}


def _remove_target(path: Path) -> None:
    link_lock = path.parent / f".{path.name}.agentmesh-link.yaml"
    if path.is_symlink() and link_lock.exists():
        link_lock.unlink()
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _inside(root: Path, candidate: Path) -> bool:
    return root == candidate or root in candidate.parents


def _action_id(history_id: str, target: str, skill: str) -> str:
    digest = hashlib.sha256(f"{history_id}\0{target}\0{skill}".encode()).hexdigest()
    return f"rb-{digest[:12]}"


def _summary(actions: list[dict[str, Any]], warnings: list[str]) -> dict[str, int]:
    blocked = sum(1 for action in actions if action["hard_block"])
    executable = sum(1 for action in actions if not action["hard_block"])
    return {
        "actions": len(actions),
        "executable": executable,
        "blocked": blocked,
        "warnings": len(warnings) + sum(len(action["warnings"]) for action in actions),
        "hard_blocks": blocked,
    }


def _error_plan(backup_ref: str, error: str, *, status: str = "error") -> dict[str, Any]:
    recoverability = "unsafe_path" if status == "blocked" and "outside" in error else "unknown"
    return {
        "schema": "agentmesh.rollback-plan/v1",
        "command": "rollback plan",
        "status": status,
        "mode": "PLAN",
        "backup": {
            "backup_ref": backup_ref,
            "backup_id": None,
            "history_id": None,
            "backup_path": None,
            "sync_mode": "unknown",
            "recoverability": recoverability,
        },
        "summary": {
            "actions": 0,
            "executable": 0,
            "blocked": 0,
            "warnings": 0,
            "hard_blocks": 1 if status == "blocked" else 0,
        },
        "actions": [],
        "warnings": [],
        "errors": [error],
        "next_steps": ["Use a backup id from `am backup list`."],
    }


def _resolve_record(
    agentmesh_home: Path, backup_ref: str
) -> tuple[dict[str, Any] | None, str | None, str]:
    records = list_backup_records(agentmesh_home)["data"]["backups"]
    if backup_ref.startswith("bkp-"):
        matches = [record for record in records if record["backup_id"] == backup_ref]
        ambiguous_error = "ambiguous_backup"
    elif backup_ref.startswith("sync-"):
        matches = [record for record in records if record["history_id"] == backup_ref]
        ambiguous_error = "ambiguous_history"
        if not matches:
            raw_matches = _raw_history_matches(agentmesh_home, backup_ref)
            if raw_matches:
                return None, "not_rollback_eligible", "error"
    else:
        backups_root = (agentmesh_home / "backups").resolve()
        raw = Path(backup_ref).expanduser()
        candidate = (backups_root / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if not _inside(backups_root, candidate):
            return (
                None,
                "backup path is outside <agentmesh_home>/backups/ and was not inspected",
                "blocked",
            )
        matches = [
            record
            for record in records
            if Path(record["backup_path"]).expanduser().resolve() == candidate
        ]
        ambiguous_error = "ambiguous_backup_path"
    if not matches:
        return None, "backup_not_found", "error"
    if len(matches) > 1:
        return None, ambiguous_error, "error"
    return matches[0], None, "ok"


def _raw_history_matches(agentmesh_home: Path, history_id: str) -> list[dict[str, Any]]:
    path = agentmesh_home / "state" / "sync-history.jsonl"
    if not path.exists():
        return []
    matches: list[dict[str, Any]] = []
    import json

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("id") == history_id:
            matches.append(value)
    return matches


def _is_managed_symlink(target: Path, skill: str, target_name: str) -> bool:
    lock = _read_link_lock(target)
    return (
        target.is_symlink()
        and lock.get("schema") == "agentmesh.link-lock/v1"
        and lock.get("mode") == "symlink"
        and lock.get("skill") == skill
        and lock.get("target") == target_name
    )


def _classify_current_target(target: Path, skill: str, target_name: str) -> tuple[str, list[str]]:
    if target.is_symlink():
        if _is_managed_symlink(target, skill, target_name):
            return "managed_symlink", ["target is an AgentMesh managed symlink"]
        return "unmanaged", ["target symlink is not managed by AgentMesh"]
    if not target.exists():
        return "missing", ["target path is missing"]
    if target.is_file():
        return "unmanaged", ["target path exists but is a file"]
    lock = target / LOCK_FILE
    if not lock.exists():
        return "unmanaged", ["target has no AgentMesh lock"]
    try:
        lock_data = read_yaml(lock)
    except Exception:
        return "unmanaged", ["target lock is unreadable"]
    if (
        lock_data.get("schema") != "agentmesh.lock/v1"
        or lock_data.get("skill") != skill
        or lock_data.get("target") != target_name
    ):
        return "unmanaged", ["target lock does not match action"]
    if _tree_hash(target) != lock_data.get("hash"):
        return "managed_drift", ["target hash differs from AgentMesh lock"]
    return "managed_clean", ["target is managed clean"]


def _decision(
    *,
    recoverability: str,
    current_target_state: str,
    backup_skill_path: Path,
    sync_mode: str,
) -> tuple[str, bool]:
    if current_target_state == "unsafe_path" or recoverability == "unsafe_path":
        return "block_unsafe_path", True
    if recoverability == "missing_path":
        return "block_missing_path", True
    if recoverability == "empty_backup":
        return "block_empty_backup", True
    if recoverability == "unknown":
        return "block_unknown", True
    if recoverability == "partial":
        return "block_partial", True
    if not backup_skill_path.exists():
        return "block_backup_missing", True
    if current_target_state == "managed_drift":
        return "block_drift", True
    if current_target_state == "unmanaged":
        return "block_unmanaged", True
    if current_target_state == "managed_symlink":
        if sync_mode == "symlink" and recoverability in {"restorable", "metadata_missing"}:
            return "restore_managed_symlink_to_tree", False
        return "block_symlink", True
    if recoverability == "metadata_missing" and current_target_state in {
        "managed_clean",
        "missing",
    }:
        return "restore_tree", False
    if current_target_state in {"managed_clean", "missing"}:
        return "restore_tree", False
    return "manual_review", True


def _safe_backup_skill_path(backup_path: Path, target_name: str, skill: str) -> tuple[Path, bool]:
    candidate = backup_path / target_name / skill
    resolved = candidate.expanduser().resolve()
    return candidate, _inside(backup_path.expanduser().resolve(), resolved)


def build_rollback_plan(
    agentmesh_home: Path,
    backup_ref: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    record, error, error_status = _resolve_record(agentmesh_home, backup_ref)
    if error or record is None:
        return _error_plan(
            backup_ref,
            error or "backup_not_found",
            status=error_status if error_status != "ok" else "error",
        )

    recoverability = record["recoverability"]["status"]
    backup_path_raw = record["backup_path"]
    backups_root = (agentmesh_home / "backups").resolve()
    backup_path = Path(backup_path_raw).expanduser().resolve()
    if not _inside(backups_root, backup_path):
        return _error_plan(
            backup_ref,
            "backup path is outside <agentmesh_home>/backups/ and was not inspected",
            status="blocked",
        )

    guard = PathGuard(agentmesh_home)
    actions: list[dict[str, Any]] = []
    warnings: list[str] = []
    for ref in record.get("action_refs", []):
        target_name = ref.get("target")
        skill = ref.get("skill")
        if not target_name or not skill:
            continue
        try:
            target_path = target_skill_path(skill, target_name, home or loader.user_home())
            guard.ensure_writable_target(target_path)
        except (ValueError, PathViolation) as exc:
            current_state = "unsafe_path"
            reasons = [str(exc)]
            target_path = Path(ref.get("target_path") or "")
        else:
            current_state, reasons = _classify_current_target(target_path, skill, target_name)

        backup_skill_path, backup_skill_safe = _safe_backup_skill_path(
            backup_path, target_name, skill
        )
        if not backup_skill_safe:
            current_state = "unsafe_path"
            reasons = ["backup skill path escapes backup root"]
            decision, hard_block = "block_unsafe_path", True
        else:
            decision, hard_block = _decision(
                recoverability=recoverability,
                current_target_state=current_state,
                backup_skill_path=backup_skill_path,
                sync_mode=str(record.get("sync_mode", "unknown")),
            )
        target_state = current_state
        if recoverability == "metadata_missing" and current_state in {"managed_clean", "missing"}:
            target_state = "metadata_missing"
        action_warnings = []
        if recoverability == "metadata_missing":
            action_warnings.append(
                "backup metadata is missing; rollback will restore the whole backup directory tree"
            )
        actions.append(
            {
                "action_id": _action_id(record["history_id"], target_name, skill),
                "target": target_name,
                "skill": skill,
                "target_path": str(target_path),
                "backup_skill_path": str(backup_skill_path),
                "target_state": target_state,
                "current_target_state": current_state,
                "recoverability": recoverability,
                "decision": decision,
                "hard_block": hard_block,
                "reasons": reasons,
                "warnings": action_warnings,
            }
        )
    if recoverability == "metadata_missing":
        warnings.append("This is a conservative tree-level rollback plan.")
    summary = _summary(actions, warnings)
    executable = actions and summary["hard_blocks"] == 0
    return {
        "schema": "agentmesh.rollback-plan/v1",
        "command": "rollback plan",
        "status": "executable" if executable else "blocked",
        "mode": "PLAN",
        "backup": {
            "backup_ref": backup_ref,
            "backup_id": record["backup_id"],
            "history_id": record["history_id"],
            "backup_path": record["backup_path"],
            "sync_mode": record.get("sync_mode", "unknown"),
            "recoverability": recoverability,
        },
        "summary": summary,
        "actions": actions,
        "warnings": warnings,
        "errors": [],
        "next_steps": [
            "Review this plan, then run `rollback apply <backup-ref> --confirm` "
            "to execute after a fresh plan rebuild."
        ]
        if executable
        else ["Resolve hard blocks before applying rollback."],
    }


def _rollback_history_file(agentmesh_home: Path) -> Path:
    return agentmesh_home / "state" / "rollback-history.jsonl"


def _snapshot_root(agentmesh_home: Path, action: dict[str, Any]) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return (
        agentmesh_home
        / "backups"
        / "rollback-current"
        / timestamp
        / str(action["target"])
        / str(action["skill"])
    )


def _snapshot_current_target(agentmesh_home: Path, action: dict[str, Any]) -> dict[str, str | bool]:
    target_path = Path(action["target_path"])
    snapshot = _snapshot_root(agentmesh_home, action)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not (target_path.exists() or target_path.is_symlink()):
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "TARGET_MISSING").write_text("true\n", encoding="utf-8")
        return {"action_id": action["action_id"], "path": str(snapshot), "target_existed": False}
    if target_path.is_symlink():
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "SYMLINK_TARGET").write_text(str(target_path.readlink()), encoding="utf-8")
        link_lock = target_path.parent / f".{target_path.name}.agentmesh-link.yaml"
        if link_lock.exists():
            shutil.copy2(link_lock, snapshot / "agentmesh-link.yaml")
    else:
        shutil.copytree(target_path, snapshot)
    return {"action_id": action["action_id"], "path": str(snapshot), "target_existed": True}


def _restore_snapshot(snapshot: dict[str, str | bool], target_path: Path) -> None:
    snapshot_path = Path(str(snapshot["path"]))
    _remove_target(target_path)
    if snapshot.get("target_existed") is False or (snapshot_path / "TARGET_MISSING").exists():
        return
    symlink_marker = snapshot_path / "SYMLINK_TARGET"
    if symlink_marker.exists():
        link_target = symlink_marker.read_text(encoding="utf-8")
        target_path.symlink_to(link_target, target_is_directory=True)
        snapshot_link_lock = snapshot_path / "agentmesh-link.yaml"
        if snapshot_link_lock.exists():
            shutil.copy2(
                snapshot_link_lock,
                target_path.parent / f".{target_path.name}.agentmesh-link.yaml",
            )
    else:
        shutil.copytree(snapshot_path, target_path)


def _recover_from_snapshots(
    snapshots: list[dict[str, str | bool]], actions: list[dict[str, Any]]
) -> None:
    actions_by_id = {action["action_id"]: action for action in actions}
    for snapshot in reversed(snapshots):
        action = actions_by_id.get(str(snapshot["action_id"]))
        if not action:
            continue
        _restore_snapshot(snapshot, Path(action["target_path"]))


def _write_restored_lock(target_path: Path, action: dict[str, Any]) -> None:
    if not target_path.exists() or target_path.is_symlink():
        return
    write_yaml(
        target_path / LOCK_FILE,
        {
            "schema": "agentmesh.lock/v1",
            "skill": action["skill"],
            "target": action["target"],
            "hash": _tree_hash(target_path),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "operation": "rollback",
            "source_backup": action.get("backup_skill_path"),
        },
    )


def _apply_restore_action(action: dict[str, Any]) -> dict[str, Any]:
    target_path = Path(action["target_path"])
    backup_path = Path(action["backup_skill_path"])
    if not backup_path.exists():
        raise RollbackApplyBlocked("backup_missing")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_target(target_path)
    shutil.copytree(backup_path, target_path)
    _write_restored_lock(target_path, action)
    return {
        "action_id": action["action_id"],
        "target": action["target"],
        "skill": action["skill"],
        "decision": action["decision"],
        "target_path": str(target_path),
        "backup_skill_path": str(backup_path),
        "status": "applied",
    }


def _append_rollback_history(agentmesh_home: Path, result: dict[str, Any]) -> None:
    path = _rollback_history_file(agentmesh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, ensure_ascii=False) + "\n")


def apply_rollback(
    agentmesh_home: Path,
    backup_ref: str,
    *,
    confirm: bool = False,
    home: Path | None = None,
) -> dict[str, Any]:
    if not confirm:
        raise RollbackApplyBlocked("confirm_required")
    plan = build_rollback_plan(agentmesh_home, backup_ref, home=home)
    if plan["status"] != "executable" or plan["summary"]["hard_blocks"]:
        raise RollbackApplyBlocked("plan_not_executable")
    for action in plan["actions"]:
        if action["hard_block"] or action["decision"] not in APPLY_DECISIONS:
            raise RollbackApplyBlocked("action_not_executable")

    applied_actions: list[dict[str, Any]] = []
    snapshots: list[dict[str, str | bool]] = []
    try:
        for action in plan["actions"]:
            snapshots.append(_snapshot_current_target(agentmesh_home, action))
            applied_actions.append(_apply_restore_action(action))

        result = {
            "schema": "agentmesh.rollback-apply/v1",
            "command": "rollback apply",
            "status": "applied",
            "mode": "APPLY",
            "backup": plan["backup"],
            "summary": {
                "actions": len(applied_actions),
                "applied": len(applied_actions),
                "blocked": 0,
                "snapshots": len(snapshots),
            },
            "actions": applied_actions,
            "snapshots": snapshots,
            "warnings": plan["warnings"],
            "errors": [],
            "next_steps": ["Inspect restored target runtime skill directories."],
        }
        _append_rollback_history(agentmesh_home, result)
    except RollbackApplyBlocked:
        raise
    except Exception as exc:
        try:
            _recover_from_snapshots(snapshots, plan["actions"])
        except Exception as recovery_exc:
            raise RollbackApplyBlocked(
                f"apply_failed_recovery_failed: {exc}; recovery_error: {recovery_exc}"
            ) from exc
        raise RollbackApplyBlocked(f"apply_failed_recovered: {exc}") from exc
    return result
