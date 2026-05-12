from __future__ import annotations

from pathlib import Path

from agentmesh.config.loader import AGENT_TARGETS, timestamp
from agentmesh.services.registry_service import skill_registry_dir
from agentmesh.utils.yaml_io import read_yaml, write_yaml

STATE_SCHEMA = "agentmesh.skills-state/v1"


class SkillStateError(ValueError):
    """Raised when skill state input is invalid."""


def skills_state_path(agentmesh_home: Path) -> Path:
    return agentmesh_home / "state" / "skills.yaml"


def load_skills_state(agentmesh_home: Path) -> dict:
    path = skills_state_path(agentmesh_home)
    if not path.exists():
        return {"schema": STATE_SCHEMA, "skills": {}}
    data = read_yaml(path)
    skills = data.get("skills")
    if not isinstance(skills, dict):
        skills = {}
    return {"schema": data.get("schema") or STATE_SCHEMA, "skills": skills}


def save_skills_state(agentmesh_home: Path, state: dict) -> None:
    write_yaml(
        skills_state_path(agentmesh_home),
        {"schema": STATE_SCHEMA, "skills": state.get("skills") or {}},
    )


def _parse_targets(targets: str) -> list[str]:
    parsed = [item.strip() for item in targets.split(",") if item.strip()]
    if not parsed:
        raise SkillStateError("至少需要指定一个 target")
    unsupported = [target for target in parsed if target not in AGENT_TARGETS]
    if unsupported:
        raise SkillStateError(f"暂不支持目标 agent：{', '.join(unsupported)}")
    return parsed


def _ensure_registry_skill(agentmesh_home: Path, skill: str) -> None:
    if not skill_registry_dir(agentmesh_home, skill).exists():
        raise SkillStateError(f"registry 中不存在 skill：{skill}")


def set_skill_targets(
    agentmesh_home: Path,
    skill: str,
    targets: str,
    *,
    enabled: bool,
    mode: str = "copy",
) -> dict:
    if mode != "copy":
        raise SkillStateError("当前 state 仅支持 copy 模式；symlink 仍需通过 sync 显式确认")
    _ensure_registry_skill(agentmesh_home, skill)
    parsed_targets = _parse_targets(targets)
    state = load_skills_state(agentmesh_home)
    skills = state.setdefault("skills", {})
    entry = skills.setdefault(skill, {"targets": {}})
    target_state = entry.setdefault("targets", {})
    updated_at = timestamp()
    for target in parsed_targets:
        target_state[target] = {"enabled": enabled, "mode": mode, "updated_at": updated_at}
    save_skills_state(agentmesh_home, state)
    return get_skill_status(agentmesh_home, skill)


def get_skill_status(agentmesh_home: Path, skill: str | None = None) -> dict:
    state = load_skills_state(agentmesh_home)
    skills = state.get("skills") or {}
    if skill is not None:
        return {"skill": skill, "targets": skills.get(skill, {}).get("targets", {})}
    return {"skills": skills}


def enabled_sync_pairs(agentmesh_home: Path) -> list[dict[str, str]]:
    state = load_skills_state(agentmesh_home)
    pairs: list[dict[str, str]] = []
    for skill, entry in sorted((state.get("skills") or {}).items()):
        if not skill_registry_dir(agentmesh_home, skill).exists():
            continue
        targets = entry.get("targets") if isinstance(entry, dict) else {}
        if not isinstance(targets, dict):
            continue
        for target, config in sorted(targets.items()):
            if target not in AGENT_TARGETS or not isinstance(config, dict):
                continue
            if config.get("enabled") is True:
                pairs.append({"skill": skill, "target": target})
    return pairs



def rename_skill_state(agentmesh_home: Path, old_name: str, new_name: str) -> None:
    """Rename a skill key inside ``state/skills.yaml``.

    No-op when the old key is absent. Raises when the new key would
    collide with an existing different entry.
    """
    state = load_skills_state(agentmesh_home)
    skills = state.get("skills") or {}
    if old_name not in skills:
        return
    if new_name in skills and new_name != old_name:
        raise SkillStateError(
            f"state 中已存在目标 skill `{new_name}`；rename 会造成冲突，请先解决"
        )
    skills[new_name] = skills.pop(old_name)
    state["skills"] = skills
    save_skills_state(agentmesh_home, state)


def remove_skill_state(agentmesh_home: Path, name: str) -> None:
    """Drop a skill from ``state/skills.yaml`` entirely. No-op when absent."""
    state = load_skills_state(agentmesh_home)
    skills = state.get("skills") or {}
    if name in skills:
        skills.pop(name)
        state["skills"] = skills
        save_skills_state(agentmesh_home, state)
