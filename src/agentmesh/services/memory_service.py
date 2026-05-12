"""MemoryMesh 服务层：跨 Agent 记忆资产 scan/import/diff/list/sync。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agentmesh.models.memory import MemoryAsset
from agentmesh.utils.yaml_io import read_yaml, write_yaml

# 各 Agent 的记忆文件定义
MEMORY_SOURCES: dict[str, dict[str, str]] = {
    "hermes": {
        "MEMORY.md": "~/.hermes/MEMORY.md",
        "USER.md": "~/.hermes/USER.md",
    },
    "openclaw": {
        "MEMORY.md": "~/.openclaw/workspace/MEMORY.md",
    },
    "codex": {
        "instructions.md": "~/.codex/instructions.md",
    },
    "claude-code": {
        "CLAUDE.md": "~/.claude/CLAUDE.md",
    },
}

MEMORY_FORMATS: dict[str, str] = {
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def _detect_format(path: Path) -> str:
    return MEMORY_FORMATS.get(path.suffix.lower(), "text")


def _compute_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def scan_memory_files(
    user_home: Path,
    agent: str = "all",
) -> list[MemoryAsset]:
    """扫描各 Agent 的记忆文件，返回 MemoryAsset 列表。"""
    agents_to_scan = list(MEMORY_SOURCES) if agent == "all" else [agent]
    if agent != "all" and agent not in MEMORY_SOURCES:
        raise ValueError(
            f"未知 agent: {agent}，可选: {', '.join(MEMORY_SOURCES)}"
        )
    results: list[MemoryAsset] = []
    for ag in agents_to_scan:
        for name, rel_path in MEMORY_SOURCES[ag].items():
            abs_path = Path(rel_path.replace("~", str(user_home)))
            if not abs_path.exists():
                continue
            content = abs_path.read_text(encoding="utf-8")
            digest = _compute_digest(content)
            results.append(
                MemoryAsset(
                    agent=ag,
                    name=name,
                    source_path=abs_path,
                    digest=digest,
                    content=content,
                    format=_detect_format(abs_path),
                    size=len(content.encode("utf-8")),
                )
            )
    return results


def _memory_registry_dir(agentmesh_home: Path) -> Path:
    return agentmesh_home / "memories"


def _memory_asset_dir(agentmesh_home: Path, agent: str, name: str) -> Path:
    return _memory_registry_dir(agentmesh_home) / agent / name


class MemoryImportConflict(RuntimeError):
    """Raised when an import would overwrite a different memory asset."""


def import_memory(
    agentmesh_home: Path,
    asset: MemoryAsset,
    *,
    dry_run: bool = False,
) -> Path | dict:
    """导入记忆资产到 AgentMesh registry。"""
    target = _memory_asset_dir(agentmesh_home, asset.agent, asset.name)
    manifest_path = target / "agentmesh.memory.yaml"
    content_path = target / "content.md"

    if dry_run:
        existing_digest = None
        if manifest_path.exists():
            try:
                existing_digest = read_yaml(manifest_path).get("digest")
            except Exception:
                existing_digest = None
        return {
            "agent": asset.agent,
            "name": asset.name,
            "source": str(asset.source_path),
            "target": str(target),
            "digest": asset.digest,
            "would_write": existing_digest != asset.digest,
            "existing_digest": existing_digest,
            "conflict": existing_digest is not None and existing_digest != asset.digest,
        }

    if manifest_path.exists():
        try:
            existing_digest = read_yaml(manifest_path).get("digest")
        except Exception:
            existing_digest = None
        if existing_digest and existing_digest != asset.digest:
            raise MemoryImportConflict(
                f"导入冲突：registry 中已存在 {asset.agent}/{asset.name}，"
                "且内容与当前来源不同；请先 diff 检查后再处理。"
            )

    target.mkdir(parents=True, exist_ok=True)
    content_path.write_text(asset.content, encoding="utf-8")
    write_yaml(
        manifest_path,
        {
            "schema": "agentmesh.memory/v1",
            "agent": asset.agent,
            "name": asset.name,
            "source_path": str(asset.source_path),
            "digest": asset.digest,
            "format": asset.format,
            "size": asset.size,
        },
    )
    return target


def list_imported_memories(agentmesh_home: Path) -> list[dict]:
    """列出 registry 中已导入的记忆资产。"""
    mem_root = _memory_registry_dir(agentmesh_home)
    results: list[dict] = []
    if not mem_root.exists():
        return results
    for agent_dir in sorted(mem_root.iterdir()):
        if not agent_dir.is_dir():
            continue
        for name_dir in sorted(agent_dir.iterdir()):
            if not name_dir.is_dir():
                continue
            manifest_path = name_dir / "agentmesh.memory.yaml"
            if manifest_path.exists():
                try:
                    meta = read_yaml(manifest_path)
                except Exception:
                    meta = {}
                results.append(
                    {
                        "agent": meta.get("agent", agent_dir.name),
                        "name": meta.get("name", name_dir.name),
                        "path": str(name_dir),
                        "digest": meta.get("digest", ""),
                        "format": meta.get("format", "unknown"),
                        "size": meta.get("size", 0),
                    }
                )
    return results


def sync_memory(
    agentmesh_home: Path,
    target: str,
    *,
    dry_run: bool = True,
    home: Path | None = None,
) -> dict:
    """将 registry 中已导入的记忆同步到目标 Agent home 目录。

    Parameters
    ----------
    agentmesh_home:
        AgentMesh registry 根目录。
    target:
        目标 agent 名称（如 hermes、openclaw）。
    dry_run:
        True 时只返回计划不写入。
    home:
        目标 agent 的 home 目录，默认 user_home()。
    """
    from agentmesh.config.loader import user_home

    actual_home = home or user_home()
    mem_root = _memory_registry_dir(agentmesh_home)
    agent_dir = mem_root / target

    if not agent_dir.exists():
        return {
            "target": target,
            "dry_run": dry_run,
            "actions": [],
            "applied": 0,
            "skipped": 0,
            "error": f"registry 中无 {target} 的记忆资产",
        }

    actions: list[dict] = []
    applied = 0
    skipped = 0

    for name_dir in sorted(agent_dir.iterdir()):
        if not name_dir.is_dir():
            continue
        manifest_path = name_dir / "agentmesh.memory.yaml"
        content_path = name_dir / "content.md"
        if not manifest_path.exists() or not content_path.exists():
            continue

        meta = read_yaml(manifest_path)
        source_name = meta.get("name", name_dir.name)
        registry_content = content_path.read_text(encoding="utf-8")

        # 确定目标文件路径
        source_path_str = meta.get("source_path", "")
        if source_path_str:
            target_file = Path(source_path_str)
            # 确保目标在 user home 下
            if not str(target_file).startswith(str(actual_home)):
                target_file = actual_home / ".hermes" / source_name
        else:
            target_file = actual_home / ".hermes" / source_name

        # 读取当前内容
        current_content = ""
        if target_file.exists():
            current_content = target_file.read_text(encoding="utf-8")

        if current_content == registry_content:
            actions.append({
                "name": source_name,
                "target_path": str(target_file),
                "status": "skipped",
                "reason": "identical",
            })
            skipped += 1
            continue

        action_info: dict = {
            "name": source_name,
            "target_path": str(target_file),
            "status": "would_apply" if dry_run else "applied",
        }
        if not dry_run:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(registry_content, encoding="utf-8")
            applied += 1
        actions.append(action_info)

    return {
        "target": target,
        "dry_run": dry_run,
        "actions": actions,
        "applied": applied,
        "skipped": skipped,
    }


def diff_memory(
    agentmesh_home: Path,
    agent_a: str,
    agent_b: str,
    name: str | None = None,
) -> dict:
    """比较两个 Agent 的记忆差异。返回结构化 diff 结果。"""
    mem_root = _memory_registry_dir(agentmesh_home)

    def _load_agent_memories(agent: str) -> dict[str, dict]:
        agent_dir = mem_root / agent
        if not agent_dir.exists():
            return {}
        result = {}
        for name_dir in sorted(agent_dir.iterdir()):
            if not name_dir.is_dir():
                continue
            manifest_path = name_dir / "agentmesh.memory.yaml"
            content_path = name_dir / "content.md"
            if manifest_path.exists():
                try:
                    meta = read_yaml(manifest_path)
                except Exception:
                    meta = {}
                content = ""
                if content_path.exists():
                    content = content_path.read_text(encoding="utf-8")
                result[name_dir.name] = {"meta": meta, "content": content}
        return result

    mems_a = _load_agent_memories(agent_a)
    mems_b = _load_agent_memories(agent_b)

    if name:
        # 单文件 diff
        entry_a = mems_a.get(name)
        entry_b = mems_b.get(name)
        if not entry_a and not entry_b:
            return {
                "agent_a": agent_a,
                "agent_b": agent_b,
                "name": name,
                "level": 0,
                "result": "not_found",
                "detail": "两个 Agent 均无此记忆资产。",
            }
        if not entry_a:
            return {
                "agent_a": agent_a,
                "agent_b": agent_b,
                "name": name,
                "level": 2,
                "result": "only_in_b",
                "detail": f"仅 {agent_b} 拥有此记忆。",
            }
        if not entry_b:
            return {
                "agent_a": agent_a,
                "agent_b": agent_b,
                "name": name,
                "level": 2,
                "result": "only_in_a",
                "detail": f"仅 {agent_a} 拥有此记忆。",
            }
        digest_a = entry_a["meta"].get("digest", "")
        digest_b = entry_b["meta"].get("digest", "")
        if digest_a == digest_b:
            return {
                "agent_a": agent_a,
                "agent_b": agent_b,
                "name": name,
                "level": 0,
                "result": "identical",
                "detail": "内容一致。",
            }
        return {
            "agent_a": agent_a,
            "agent_b": agent_b,
            "name": name,
            "level": 1,
            "result": "different",
            "detail": "内容不同。",
            "digest_a": digest_a,
            "digest_b": digest_b,
            "size_a": entry_a["meta"].get("size", 0),
            "size_b": entry_b["meta"].get("size", 0),
        }

    # 全量 diff
    all_names = sorted(set(mems_a) | set(mems_b))
    only_a = [n for n in all_names if n in mems_a and n not in mems_b]
    only_b = [n for n in all_names if n in mems_b and n not in mems_a]
    shared = [n for n in all_names if n in mems_a and n in mems_b]
    different = [
        n
        for n in shared
        if mems_a[n]["meta"].get("digest") != mems_b[n]["meta"].get("digest")
    ]
    identical = [n for n in shared if n not in different]

    return {
        "agent_a": agent_a,
        "agent_b": agent_b,
        "only_in_a": only_a,
        "only_in_b": only_b,
        "different": different,
        "identical": identical,
        "summary": {
            "total_a": len(mems_a),
            "total_b": len(mems_b),
            "only_a": len(only_a),
            "only_b": len(only_b),
            "different": len(different),
            "identical": len(identical),
        },
    }
