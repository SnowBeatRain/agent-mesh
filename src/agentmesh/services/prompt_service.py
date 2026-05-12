from __future__ import annotations

from pathlib import Path

from agentmesh.config.loader import timestamp, user_home
from agentmesh.utils.hashing import hash_bytes
from agentmesh.utils.naming import validate_skill_name
from agentmesh.utils.yaml_io import read_yaml, write_yaml

PROMPT_SCHEMA = "agentmesh.prompt/v1"
PROMPT_STATE_SCHEMA = "agentmesh.prompts-state/v1"
PROMPT_TARGETS: dict[str, tuple[tuple[str, ...], str]] = {
    "codex": ((".codex",), "AGENTS.md"),
    "claude-code": ((".claude",), "CLAUDE.md"),
    "hermes": ((".hermes",), "AGENTS.md"),
    "openclaw": ((".openclaw",), "AGENTS.md"),
}


class PromptError(ValueError):
    """Raised when prompt operations cannot be completed safely."""


def prompts_root(agentmesh_home: Path) -> Path:
    return agentmesh_home / "prompts"


def prompt_dir(agentmesh_home: Path, prompt_id: str) -> Path:
    return prompts_root(agentmesh_home) / prompt_id


def prompt_state_path(agentmesh_home: Path) -> Path:
    return agentmesh_home / "state" / "prompts.yaml"


def live_prompt_path(target: str, home: Path | None = None) -> Path:
    try:
        parts, filename = PROMPT_TARGETS[target]
    except KeyError as exc:
        raise PromptError(f"暂不支持 prompt target：{target}") from exc
    return (home or user_home()).joinpath(*parts, filename)


def load_prompt_state(agentmesh_home: Path) -> dict:
    path = prompt_state_path(agentmesh_home)
    if not path.exists():
        return {"schema": PROMPT_STATE_SCHEMA, "targets": {}}
    data = read_yaml(path)
    targets = data.get("targets")
    if not isinstance(targets, dict):
        targets = {}
    return {"schema": data.get("schema") or PROMPT_STATE_SCHEMA, "targets": targets}


def save_prompt_state(agentmesh_home: Path, state: dict) -> None:
    write_yaml(
        prompt_state_path(agentmesh_home),
        {"schema": PROMPT_STATE_SCHEMA, "targets": state.get("targets") or {}},
    )


def _prompt_meta_path(agentmesh_home: Path, prompt_id: str) -> Path:
    return prompt_dir(agentmesh_home, prompt_id) / "prompt.yaml"


def _prompt_content_path(agentmesh_home: Path, prompt_id: str) -> Path:
    return prompt_dir(agentmesh_home, prompt_id) / "PROMPT.md"


def _read_prompt(agentmesh_home: Path, prompt_id: str) -> dict:
    meta_path = _prompt_meta_path(agentmesh_home, prompt_id)
    content_path = _prompt_content_path(agentmesh_home, prompt_id)
    if not meta_path.exists() or not content_path.exists():
        raise PromptError(f"registry 中不存在 prompt：{prompt_id}")
    meta = read_yaml(meta_path)
    meta["content"] = content_path.read_text(encoding="utf-8")
    return meta


def _versions_dir(agentmesh_home: Path, prompt_id: str) -> Path:
    return prompt_dir(agentmesh_home, prompt_id) / "versions"


def add_prompt(
    agentmesh_home: Path,
    prompt_id: str,
    name: str,
    content: str,
    description: str = "",
) -> dict:
    prompt_id = validate_skill_name(prompt_id)
    directory = prompt_dir(agentmesh_home, prompt_id)
    if directory.exists():
        raise PromptError(f"prompt 已存在：{prompt_id}")
    directory.mkdir(parents=True, exist_ok=True)
    now = timestamp()
    content_hash = hash_bytes(content.encode("utf-8"))
    meta = {
        "schema": PROMPT_SCHEMA,
        "id": prompt_id,
        "name": name,
        "description": description,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "content_hash": content_hash,
    }
    write_yaml(_prompt_meta_path(agentmesh_home, prompt_id), meta)
    _prompt_content_path(agentmesh_home, prompt_id).write_text(content, encoding="utf-8")
    # 保存 v1 到版本目录
    vdir = _versions_dir(agentmesh_home, prompt_id)
    vdir.mkdir(parents=True, exist_ok=True)
    write_yaml(
        vdir / "v1.yaml",
        {
            "version": 1,
            "content_hash": content_hash,
            "name": name,
            "description": description,
            "created_at": now,
        },
    )
    (vdir / "v1.md").write_text(content, encoding="utf-8")
    return {**meta, "content_path": str(_prompt_content_path(agentmesh_home, prompt_id))}


def list_prompts(agentmesh_home: Path) -> list[dict]:
    root = prompts_root(agentmesh_home)
    if not root.exists():
        return []
    prompts: list[dict] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        meta_path = directory / "prompt.yaml"
        if not meta_path.exists():
            continue
        meta = read_yaml(meta_path)
        prompts.append(
            {
                "id": meta.get("id") or directory.name,
                "name": meta.get("name") or directory.name,
                "description": meta.get("description") or "",
                "content_hash": meta.get("content_hash") or "",
            }
        )
    return prompts


def update_prompt(
    agentmesh_home: Path,
    prompt_id: str,
    *,
    content: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> dict:
    """更新 prompt，创建新版本。内容相同时抛出 PromptError。"""
    meta_path = _prompt_meta_path(agentmesh_home, prompt_id)
    content_path = _prompt_content_path(agentmesh_home, prompt_id)
    if not meta_path.exists() or not content_path.exists():
        raise PromptError(f"registry 中不存在 prompt：{prompt_id}")
    meta = read_yaml(meta_path)
    current_content = content_path.read_text(encoding="utf-8")

    new_content = content if content is not None else current_content
    new_name = name if name is not None else meta.get("name", prompt_id)
    new_description = description if description is not None else meta.get("description", "")

    new_hash = hash_bytes(new_content.encode("utf-8"))
    if new_content == current_content and name is None and description is None:
        raise PromptError("无变更：内容、名称和描述均未修改")

    now = timestamp()
    new_version = (meta.get("version") or 1) + 1
    meta["name"] = new_name
    meta["description"] = new_description
    meta["updated_at"] = now
    meta["version"] = new_version
    meta["content_hash"] = new_hash
    write_yaml(meta_path, meta)
    content_path.write_text(new_content, encoding="utf-8")

    # 保存版本快照
    vdir = _versions_dir(agentmesh_home, prompt_id)
    vdir.mkdir(parents=True, exist_ok=True)
    write_yaml(
        vdir / f"v{new_version}.yaml",
        {
            "version": new_version,
            "content_hash": new_hash,
            "name": new_name,
            "description": new_description,
            "created_at": now,
        },
    )
    (vdir / f"v{new_version}.md").write_text(new_content, encoding="utf-8")

    return {
        "schema": PROMPT_SCHEMA,
        "id": prompt_id,
        "name": new_name,
        "description": new_description,
        "version": new_version,
        "content_hash": new_hash,
        "updated_at": now,
    }


def list_prompt_versions(agentmesh_home: Path, prompt_id: str) -> list[dict]:
    """列出 prompt 的所有版本。"""
    vdir = _versions_dir(agentmesh_home, prompt_id)
    if not vdir.exists():
        # 回退到单版本
        meta_path = _prompt_meta_path(agentmesh_home, prompt_id)
        if not meta_path.exists():
            raise PromptError(f"registry 中不存在 prompt：{prompt_id}")
        meta = read_yaml(meta_path)
        return [
            {
                "version": 1,
                "content_hash": meta.get("content_hash", ""),
                "created_at": meta.get("created_at", ""),
            }
        ]
    versions = []
    for vfile in sorted(vdir.glob("v*.yaml")):
        vdata = read_yaml(vfile)
        versions.append(vdata)
    return versions


def _detect_conflict(
    agentmesh_home: Path,
    target: str,
    live_path: Path,
    prompt_content: str,
    state_entry: dict | None,
) -> dict:
    """检测 target 是否存在冲突。"""
    if not live_path.exists():
        return {"conflict": False}
    live_content = live_path.read_text(encoding="utf-8")
    live_hash = hash_bytes(live_content.encode("utf-8"))
    prompt_hash = hash_bytes(prompt_content.encode("utf-8"))
    if live_hash == prompt_hash:
        return {"conflict": False}
    # 判断是否为 managed（我们之前 enable 过的）
    managed = bool(state_entry and state_entry.get("enabled_prompt"))
    return {
        "conflict": True,
        "conflict_level": "unmanaged" if not managed else "content_changed",
        "live_hash": live_hash,
        "live_size": len(live_content),
    }


def _snapshot_live_prompt(
    agentmesh_home: Path,
    target: str,
    live_path: Path,
    state_entry: dict | None,
    *,
    apply: bool = True,
) -> dict | None:
    if not live_path.exists():
        return None
    content = live_path.read_text(encoding="utf-8")
    if not content.strip():
        return None
    current_hash = hash_bytes(content.encode("utf-8"))
    if state_entry and state_entry.get("live_hash") == current_hash:
        return None
    prompt_id = f"imported-live-{target}-{timestamp()}".replace("_", "-")
    if not apply:
        return {
            "id": prompt_id,
            "name": f"Imported live prompt for {target}",
            "description": "启用新 prompt 前自动回填的 live 文件快照。",
            "content_hash": current_hash,
            "would_create": True,
        }
    snapshot = add_prompt(
        agentmesh_home,
        prompt_id,
        f"Imported live prompt for {target}",
        content,
        "启用新 prompt 前自动回填的 live 文件快照。",
    )
    snapshot["would_create"] = False
    return snapshot


def enable_prompt(
    agentmesh_home: Path,
    prompt_id: str,
    target: str,
    *,
    apply: bool = False,
    home: Path | None = None,
    conflict_strategy: str = "backup",
) -> dict:
    prompt = _read_prompt(agentmesh_home, prompt_id)
    live_path = live_prompt_path(target, home)
    state = load_prompt_state(agentmesh_home)
    targets = state.setdefault("targets", {})
    previous = targets.get(target) if isinstance(targets.get(target), dict) else None
    content = str(prompt["content"])
    live_hash = hash_bytes(content.encode("utf-8"))

    # 冲突检测
    conflict_info = _detect_conflict(agentmesh_home, target, live_path, content, previous)

    plan = {
        "target": target,
        "prompt": prompt_id,
        "live_path": str(live_path),
        "apply": apply,
        "snapshot": None,
        "will_write": apply,
        "conflict": conflict_info["conflict"],
        "conflict_strategy": conflict_strategy,
        "skipped": False,
    }
    if conflict_info["conflict"]:
        plan["conflict_level"] = conflict_info.get("conflict_level", "unknown")
        plan["conflict_live_hash"] = conflict_info.get("live_hash")

    # dry-run 或 skip 策略冲突时不写入
    if not apply:
        return plan
    if conflict_info["conflict"] and conflict_strategy == "skip":
        plan["skipped"] = True
        return plan

    # snapshot（仅 backup 策略且存在冲突时）
    snapshot = None
    if conflict_info["conflict"] and conflict_strategy == "backup":
        snapshot = _snapshot_live_prompt(agentmesh_home, target, live_path, previous, apply=True)
    elif not conflict_info["conflict"]:
        # 无冲突时也按旧逻辑 snapshot
        snapshot = _snapshot_live_prompt(agentmesh_home, target, live_path, previous, apply=True)

    live_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if live_path.exists() and conflict_strategy == "backup":
        backup_dir = agentmesh_home / "backups" / "prompts" / timestamp()
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / live_path.name
        backup_path.write_text(live_path.read_text(encoding="utf-8"), encoding="utf-8")
    live_path.write_text(content, encoding="utf-8")
    targets[target] = {
        "enabled_prompt": prompt_id,
        "live_path": str(live_path),
        "live_hash": live_hash,
        "updated_at": timestamp(),
    }
    save_prompt_state(agentmesh_home, state)
    plan["snapshot"] = snapshot
    plan["backup_path"] = str(backup_path) if backup_path else None
    plan["live_hash"] = live_hash
    return plan


def enable_prompt_multi(
    agentmesh_home: Path,
    prompt_id: str,
    targets: list[str],
    *,
    apply: bool = False,
    home: Path | None = None,
    conflict_strategy: str = "backup",
) -> list[dict]:
    """将 prompt 同步到多个 target。"""
    plans = []
    for target in targets:
        plan = enable_prompt(
            agentmesh_home,
            prompt_id,
            target,
            apply=apply,
            home=home,
            conflict_strategy=conflict_strategy,
        )
        plans.append(plan)
    return plans


def _current_live_hash(live_path: Path) -> str | None:
    if not live_path.exists():
        return None
    return hash_bytes(live_path.read_text(encoding="utf-8").encode("utf-8"))


def prompt_target_status(agentmesh_home: Path, target: str, *, home: Path | None = None) -> dict:
    live_path = live_prompt_path(target, home)
    state = load_prompt_state(agentmesh_home)
    entry = state.get("targets", {}).get(target)
    if not isinstance(entry, dict):
        entry = {}
    live_hash = _current_live_hash(live_path)
    state_hash = entry.get("live_hash")
    enabled_prompt = entry.get("enabled_prompt")
    disabled = bool(entry.get("disabled"))
    enabled = bool(enabled_prompt) and not disabled
    managed = bool(entry)
    drift = bool(enabled and live_hash and state_hash and live_hash != state_hash)
    drift_unknown = bool(enabled and live_hash and not state_hash)
    reason = "live-hash-drift" if drift else "ok"
    if enabled and live_hash is None:
        reason = "live-missing"
    elif drift_unknown:
        reason = "state-hash-missing"
    elif not enabled:
        reason = "disabled" if disabled else "not-enabled"
    return {
        "schema": "agentmesh.prompt-target-status/v1",
        "target": target,
        "live_path": str(live_path),
        "live_exists": live_path.exists(),
        "enabled": enabled,
        "enabled_prompt": enabled_prompt if enabled else None,
        "managed": managed,
        "drift": drift,
        "drift_unknown": drift_unknown,
        "live_hash": live_hash,
        "state_live_hash": state_hash,
        "last_snapshot_prompt": entry.get("last_snapshot_prompt"),
        "updated_at": entry.get("updated_at"),
        "disabled_at": entry.get("disabled_at"),
        "reason": reason,
    }


def disable_prompt_target(
    agentmesh_home: Path,
    target: str,
    *,
    apply: bool = False,
    home: Path | None = None,
) -> dict:
    live_path = live_prompt_path(target, home)
    state = load_prompt_state(agentmesh_home)
    targets = state.setdefault("targets", {})
    previous = targets.get(target) if isinstance(targets.get(target), dict) else None
    snapshot = _snapshot_live_prompt(agentmesh_home, target, live_path, previous, apply=apply)
    plan = {
        "schema": "agentmesh.prompts-disable/v1",
        "target": target,
        "live_path": str(live_path),
        "apply": apply,
        "applied": False,
        "snapshot": snapshot,
        "will_disable_state": True,
        "will_delete_live": False,
    }
    if not apply:
        return plan
    entry = dict(previous or {})
    entry["enabled_prompt"] = None
    entry["disabled"] = True
    entry["disabled_at"] = timestamp()
    entry["live_path"] = str(live_path)
    entry["live_hash"] = _current_live_hash(live_path)
    if snapshot is not None:
        entry["last_snapshot_prompt"] = snapshot["id"]
    targets[target] = entry
    save_prompt_state(agentmesh_home, state)
    plan["applied"] = True
    plan["live_hash"] = entry["live_hash"]
    return plan


def import_live_prompt(agentmesh_home: Path, target: str, *, home: Path | None = None) -> dict:
    live_path = live_prompt_path(target, home)
    if not live_path.exists():
        raise PromptError(f"live prompt 文件不存在：{live_path}")
    content = live_path.read_text(encoding="utf-8")
    if not content.strip():
        raise PromptError(f"live prompt 文件为空：{live_path}")
    prompt_id = f"imported-live-{target}-{timestamp()}".replace("_", "-")
    return add_prompt(
        agentmesh_home,
        prompt_id,
        f"Imported live prompt for {target}",
        content,
        "从目标 runtime live prompt 文件导入。",
    )
