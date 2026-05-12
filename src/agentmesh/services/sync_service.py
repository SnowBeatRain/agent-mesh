from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from shutil import copytree

from agentmesh.config import loader
from agentmesh.config.loader import (
    AGENT_TARGETS,
    EXPORT_ONLY_TARGETS,
    registry_root,
    registry_skills_root,
    timestamp,
)
from agentmesh.engine.conflict_resolver import ConflictLevel
from agentmesh.engine.diff_engine import diff_skill
from agentmesh.paths.guard import PathGuard
from agentmesh.policy.service import evaluate_findings
from agentmesh.services.registry_service import (
    list_registry_skills,
    resolve_skill_registry_dir,
)
from agentmesh.utils.yaml_io import read_yaml, write_yaml

# ---------------------------------------------------------------------------
# Lockfile layout
# ---------------------------------------------------------------------------
# AgentMesh keeps two physically distinct lockfiles because copy and symlink
# targets have different write semantics:
#
#   • copy mode (most targets): target is a real directory. We drop
#     ``.agentmesh-lock.yaml`` (``LOCK_FILE``) *inside* it, containing the
#     hash of the copied tree. This is what drift detection reads back on
#     the next sync.
#
#   • symlink mode: target is a symbolic link into the registry. Writing
#     inside the target would mutate the registry itself, so we instead
#     store a sidecar next to it, named ``.<target>.agentmesh-link.yaml``
#     (see ``_link_lock_path``). ``LINK_LOCK_SUFFIX`` owns that convention.
#
# Switching a skill from copy to symlink (or vice versa) always tears down
# the old lockfile before writing the new one — see ``_apply_action`` and
# its rollback path. We intentionally do *not* migrate one lock format into
# the other; a mode flip regenerates from scratch.
LOCK_FILE = ".agentmesh-lock.yaml"
LINK_LOCK_SUFFIX = ".agentmesh-link.yaml"
APPLY_BLOCK_LEVELS = {
    ConflictLevel.CONTENT_CHANGED,
    ConflictLevel.MANUAL_REVIEW,
    ConflictLevel.SECURITY_BLOCK,
}


class SyncBlocked(RuntimeError):
    """Raised when policy, security, or drift checks block sync."""


class UnsupportedSyncTarget(SyncBlocked):
    """Raised when a sync target is not supported."""


class UnsupportedSyncMode(SyncBlocked):
    """Raised when sync mode is unsupported or unsafe without confirmation."""


def _target_parts(target: str) -> tuple[str, ...]:
    try:
        return AGENT_TARGETS[target]
    except KeyError as exc:
        raise UnsupportedSyncTarget(f"暂不支持目标 agent：{target}") from exc


def build_sync_plan(
    agentmesh_home: Path,
    targets: list[str],
    pairs: list[dict[str, str]] | None = None,
    sync_mode: str = "copy",
) -> list[dict]:
    actions: list[dict] = []
    if pairs is not None:
        for pair in pairs:
            skill = pair["skill"]
            target = pair["target"]
            actions.append(
                {
                    "action": sync_mode,
                    "skill": skill,
                    "to": target,
                    "target_parts": _target_parts(target),
                }
            )
        return actions
    for skill_dir in list_registry_skills(agentmesh_home):
        for target in targets:
            parts = _target_parts(target)
            actions.append(
                {
                    "action": sync_mode,
                    "skill": skill_dir.name,
                    "to": target,
                    "target_parts": parts,
                }
            )
    return actions


def render_sync_plan(
    agentmesh_home: Path,
    targets: list[str],
    mode: str = "DRY-RUN",
    home: Path | None = None,
    pairs: list[dict[str, str]] | None = None,
    sync_mode: str = "copy",
) -> dict:
    actions = [
        _render_action(agentmesh_home, action, home)
        for action in build_sync_plan(agentmesh_home, targets, pairs, sync_mode)
    ]
    blocked = [action for action in actions if action["decision"] == "block"]
    warnings = sum(action["policy"].get("warning_count", 0) for action in actions)
    return {
        "mode": mode,
        "summary": {
            "actions": len(actions),
            "allowed": len(actions) - len(blocked),
            "blocked": len(blocked),
            "warnings": warnings,
        },
        "actions": actions,
    }


def _render_action(agentmesh_home: Path, action: dict, home: Path | None = None) -> dict:
    source = resolve_skill_registry_dir(agentmesh_home, action["skill"])
    policy = evaluate_findings(source).to_dict()
    diff = diff_skill(agentmesh_home, action["skill"], action["to"], home)
    blocked_reasons: list[str] = []
    if not policy["allowed"]:
        blocked_reasons.append("policy:block")
    if diff.level in APPLY_BLOCK_LEVELS:
        blocked_reasons.append(f"conflict:{diff.name}")
    rendered = {
        "action": action["action"],
        "skill": action["skill"],
        "to": action["to"],
        "target_parts": action["target_parts"],
        "target_path": str(
            (home or loader.user_home()).joinpath(*action["target_parts"], action["skill"])
        ),
        "decision": "block" if blocked_reasons else "allow",
        "blocked_reasons": blocked_reasons,
        "diff": {
            "level": int(diff.level),
            "name": diff.name,
            "summary": diff.summary,
            "changes": diff.changes or [],
        },
        "policy": policy,
    }
    return rendered


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.relative_to(path.parent).as_posix().encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return ""
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != LOCK_FILE):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_digest(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _read_lock_hash(lock: Path) -> str | None:
    if not lock.exists():
        return None
    return read_yaml(lock).get("hash")


def _check_drift(target: Path) -> None:
    lock = target / LOCK_FILE
    locked_hash = _read_lock_hash(lock)
    if locked_hash is None:
        return
    current_hash = _tree_hash(target)
    if current_hash != locked_hash:
        raise SyncBlocked("drift detected: target changed since last AgentMesh sync")


def _check_security(source: Path) -> None:
    decision = evaluate_findings(source)
    if not decision.allowed:
        raise SyncBlocked("security block: source contains blocked audit findings")


def _write_lock(target: Path, skill: str, target_name: str, source_hash: str) -> None:
    write_yaml(
        target / LOCK_FILE,
        {
            "schema": "agentmesh.lock/v1",
            "skill": skill,
            "target": target_name,
            "hash": source_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _link_lock_path(target: Path) -> Path:
    """Sidecar path for symlink-mode lockfile. Lives next to the target link,
    not inside it, so we never write through the symlink into the registry."""
    return target.parent / f".{target.name}{LINK_LOCK_SUFFIX}"


def _read_link_lock(target: Path) -> dict:
    lock = _link_lock_path(target)
    return read_yaml(lock) if lock.exists() else {}


def _is_managed_symlink(target: Path, skill: str, target_name: str) -> bool:
    lock = _read_link_lock(target)
    return (
        target.is_symlink()
        and lock.get("schema") == "agentmesh.link-lock/v1"
        and lock.get("mode") == "symlink"
        and lock.get("skill") == skill
        and lock.get("target") == target_name
    )


def _write_link_lock(target: Path, skill: str, target_name: str, source: Path) -> None:
    write_yaml(
        _link_lock_path(target),
        {
            "schema": "agentmesh.link-lock/v1",
            "skill": skill,
            "target": target_name,
            "mode": "symlink",
            "source_path": str(source),
            "source_hash": _tree_hash(source),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _remove_link_lock(target: Path) -> None:
    lock = _link_lock_path(target)
    if lock.exists():
        lock.unlink()


def _remove_target(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)


def _restore_backup(backup: Path, target: Path) -> None:
    _remove_target(target)
    if backup.exists():
        shutil.copytree(backup, target)


def _restore_symlink(target: Path, link_target: Path | None) -> None:
    _remove_target(target)
    if link_target is not None:
        target.symlink_to(link_target, target_is_directory=True)


def _preflight_action(
    agentmesh_home: Path,
    action: dict,
    guard: PathGuard,
    *,
    allow_conflicts: bool,
    home: Path | None,
) -> tuple[Path, Path] | None:
    """Run all pre-write checks shared by copy and symlink apply paths.

    Returns ``(source, target)`` when the action should proceed, ``None`` when
    diff == IDENTICAL (skipped). Raises ``SyncBlocked`` when any gate fails.
    """
    source = resolve_skill_registry_dir(agentmesh_home, action["skill"])
    guard.ensure_inside(registry_skills_root(agentmesh_home), source)
    target = (home or loader.user_home()).joinpath(*action["target_parts"], action["skill"])
    guard.ensure_writable_target(target)
    _check_security(source)

    if target.exists() and target.is_file() and not target.is_symlink():
        raise SyncBlocked("target path exists but is not a skill directory")
    if target.is_symlink():
        if not _is_managed_symlink(target, action["skill"], action["to"]):
            raise SyncBlocked("target symlink exists but is not managed by AgentMesh")
    elif target.exists():
        _check_drift(target)

    diff = diff_skill(agentmesh_home, action["skill"], action["to"], home)
    if diff.level == ConflictLevel.IDENTICAL:
        return None
    if diff.level in APPLY_BLOCK_LEVELS and not allow_conflicts:
        raise SyncBlocked(f"conflict block: {diff.name}")
    if diff.level == ConflictLevel.SECURITY_BLOCK:
        raise SyncBlocked("security block: source contains blocked audit findings")
    return source, target


def _snapshot_target(target: Path, backup: Path) -> tuple[bool, Path | None]:
    """Capture prior state so a failed write can be rolled back.

    Returns (had_target, previous_link). Directory contents are copied to
    ``backup`` when target was a real directory; symlinks are remembered
    via ``readlink`` and restored in place on failure.
    """
    had_target = target.exists() or target.is_symlink()
    previous_link = target.readlink() if target.is_symlink() else None
    if had_target and not target.is_symlink():
        copytree(target, backup, dirs_exist_ok=True)
    return had_target, previous_link


def _rollback_target(
    target: Path, backup: Path, *, had_target: bool, previous_link: Path | None
) -> None:
    if previous_link is not None:
        _restore_symlink(target, previous_link)
    elif had_target:
        _restore_backup(backup, target)
    elif target.exists() or target.is_symlink():
        _remove_target(target)


def _apply_action(
    agentmesh_home: Path,
    action: dict,
    backup_root: Path,
    guard: PathGuard,
    *,
    allow_conflicts: bool = False,
    home: Path | None = None,
    mode: str = "copy",
) -> dict | None:
    """Execute a single sync action. ``mode`` selects copy vs symlink write.

    The preflight (path guard, security, drift, conflict) and the
    backup/rollback scaffolding are shared between both modes; only the final
    "materialize at target" step differs.
    """
    preflight = _preflight_action(
        agentmesh_home, action, guard, allow_conflicts=allow_conflicts, home=home
    )
    if preflight is None:
        return {"skipped": True, "reason": "content_identical"}
    source, target = preflight

    backup = backup_root / action["to"] / action["skill"]
    had_target, previous_link = _snapshot_target(target, backup)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _remove_target(target)
        if mode == "symlink":
            target.symlink_to(source.resolve(), target_is_directory=True)
            _write_link_lock(target, action["skill"], action["to"], source)
        else:
            copytree(source, target)
            _write_lock(target, action["skill"], action["to"], _tree_hash(target))
            _remove_link_lock(target)
    except OSError as exc:
        _rollback_target(target, backup, had_target=had_target, previous_link=previous_link)
        if mode == "symlink":
            raise SyncBlocked(f"symlink failed: {exc}") from exc
        raise
    except Exception:
        _rollback_target(target, backup, had_target=had_target, previous_link=previous_link)
        raise
    return None


def _history_file(agentmesh_home: Path) -> Path:
    return agentmesh_home / "state" / "sync-history.jsonl"


def list_sync_history(agentmesh_home: Path) -> list[dict]:
    path = _history_file(agentmesh_home)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _history_action(action: dict, *, compact: bool = False) -> dict:
    if not compact:
        return action
    diff = action.get("diff", {})
    policy = action.get("policy", {})
    result = {
        "action": action.get("action"),
        "skill": action.get("skill"),
        "to": action.get("to"),
        "target_path": action.get("target_path"),
        "decision": action.get("decision"),
        "blocked_reasons": list(action.get("blocked_reasons", [])),
        "diff": {
            "level": diff.get("level"),
            "name": diff.get("name"),
            "summary": diff.get("summary"),
        },
        "policy": {
            "allowed": policy.get("allowed"),
            "blocked_count": policy.get("blocked_count", 0),
            "warning_count": policy.get("warning_count", 0),
            "info_count": policy.get("info_count", 0),
        },
    }
    if action.get("skipped_reason"):
        result["skipped_reason"] = action["skipped_reason"]
    return result


def _history_actions(rendered_plan: dict, *, compact: bool = False) -> list[dict]:
    return [_history_action(action, compact=compact) for action in rendered_plan["actions"]]


def _annotate_skipped_action(rendered_plan: dict, action: dict, reason: str) -> None:
    """Mark a rendered action as skipped in the plan."""
    for rendered in rendered_plan.get("actions", []):
        if rendered.get("skill") == action["skill"] and rendered.get("to") == action["to"]:
            rendered["decision"] = "skip"
            rendered["skipped_reason"] = reason
            break


def _annotate_applied_action(rendered_plan: dict, action: dict) -> None:
    """Mark a rendered action as applied (may override block decision)."""
    for rendered in rendered_plan.get("actions", []):
        if rendered.get("skill") == action["skill"] and rendered.get("to") == action["to"]:
            if rendered.get("decision") == "block":
                rendered["decision"] = "allow"
                rendered["overridden"] = True
            break


def _append_sync_history(
    agentmesh_home: Path,
    *,
    targets: list[str],
    rendered_plan: dict,
    status: str = "applied",
    error: BaseException | None = None,
    actions_state: dict | None = None,
    recovery: dict | None = None,
) -> None:
    timestamp_value = datetime.now(timezone.utc).isoformat()
    entry = {
        "schema": "agentmesh.sync-history-entry/v1",
        "id": f"sync-{timestamp_value}",
        "timestamp": timestamp_value,
        "operation": "skills sync",
        "status": status,
        "targets": targets,
        "sync_mode": rendered_plan["sync_mode"],
        "summary": rendered_plan["summary"],
        "backup": rendered_plan.get("backup"),
        "actions": _json_safe(_history_actions(rendered_plan, compact=status != "applied")),
    }
    if error is not None:
        entry["error"] = {"type": type(error).__name__, "message": str(error)}
    if actions_state is not None:
        entry["actions_state"] = _json_safe(actions_state)
    if recovery is not None:
        entry["recovery"] = _json_safe(recovery)
    path = _history_file(agentmesh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def sync(
    agentmesh_home: Path,
    targets: list[str],
    apply: bool = False,
    *,
    allow_conflicts: bool = False,
    mode: str = "copy",
    confirm: bool = False,
    home: Path | None = None,
    pairs: list[dict[str, str]] | None = None,
) -> dict:
    if mode not in {"copy", "symlink"}:
        raise UnsupportedSyncMode(f"暂不支持同步模式：{mode}")
    if mode == "symlink":
        if apply and not confirm:
            raise UnsupportedSyncMode("symlink 模式需要显式 --confirm 才能 apply")
    # Export-only 目标（例如 claude-code）不允许 sync --apply，
    # 改由 `skills export <target>` 走 package 导出流程。
    if apply:
        blocked_export_only = [target for target in targets if target in EXPORT_ONLY_TARGETS]
        if blocked_export_only:
            raise UnsupportedSyncMode(
                "目标 "
                + ", ".join(sorted(blocked_export_only))
                + " 为 export-only，禁止 sync --apply；"
                "请使用 `agentmesh skills export <target> --out <path>` 生成 package。"
            )
    rendered_plan = render_sync_plan(
        agentmesh_home,
        targets,
        mode="APPLY" if apply else "DRY-RUN",
        home=home,
        pairs=pairs,
        sync_mode=mode,
    )
    rendered_plan["sync_mode"] = mode
    if not apply:
        return rendered_plan
    guard = PathGuard(registry_root(agentmesh_home))
    backup_root = agentmesh_home / "backups" / timestamp()
    rendered_plan["backup"] = str(backup_root)
    actions_state = {"attempted": [], "applied": [], "failed": [], "skipped": []}
    try:
        for action in build_sync_plan(agentmesh_home, targets, pairs, mode):
            action_key = f"{action['to']}:{action['skill']}"
            actions_state["attempted"].append(action_key)
            result = _apply_action(
                agentmesh_home,
                action,
                backup_root,
                guard,
                allow_conflicts=allow_conflicts,
                home=home,
                mode=mode,
            )
            if isinstance(result, dict) and result.get("skipped"):
                actions_state["skipped"].append(action_key)
                _annotate_skipped_action(rendered_plan, action, result["reason"])
            else:
                actions_state["applied"].append(action_key)
                _annotate_applied_action(rendered_plan, action)
    except Exception as exc:
        if actions_state["attempted"] and (not actions_state["failed"]):
            actions_state["failed"].append(actions_state["attempted"][-1])
        status = "blocked" if isinstance(exc, SyncBlocked) else "failed"
        _append_sync_history(
            agentmesh_home,
            targets=targets,
            rendered_plan=rendered_plan,
            status=status,
            error=exc,
            actions_state=actions_state,
            recovery={
                "attempted": status == "failed",
                "guarantee": "best_effort",
                "strategy": "best_effort_restore_previous_target_or_remove_partial_target",
            },
        )
        raise
    if actions_state["skipped"]:
        rendered_plan["summary"]["skipped"] = len(actions_state["skipped"])
    all_skipped = len(actions_state["skipped"]) > 0 and len(actions_state["applied"]) == 0
    _append_sync_history(
        agentmesh_home,
        targets=targets,
        rendered_plan=rendered_plan,
        status="skipped" if all_skipped else "applied",
        actions_state=actions_state,
    )
    return rendered_plan
