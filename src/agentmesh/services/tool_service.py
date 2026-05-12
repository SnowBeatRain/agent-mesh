"""ToolMesh 服务：扫描和比较各 Agent 的工具配置。"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from ruamel.yaml import YAML

from agentmesh.models.tool_config import ToolConfig, ToolDiff

_yaml = YAML(typ="safe")

# 各 Agent 工具配置的路径和解析逻辑
_CONFIG_ENTRIES: list[dict[str, object]] = [
    {
        "agent": "hermes",
        "path": (".hermes", "config.yaml"),
        "format": "yaml",
    },
    {
        "agent": "openclaw",
        "path": (".openclaw", "openclaw.json"),
        "format": "json",
    },
]


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return _yaml.load(f) or {}


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_hermes(data: dict) -> ToolConfig | None:
    """解析 Hermes 的工具配置。

    toolsets 是顶层列表，agent.disabled_toolsets 是禁用列表。
    如果没有 toolsets 段，说明没有工具配置。
    """
    toolsets = data.get("toolsets")
    if toolsets is None:
        return None
    disabled = data.get("agent", {}).get("disabled_toolsets", []) or []
    return ToolConfig(
        agent="hermes",
        tools=tuple(str(t) for t in toolsets),
        disabled_tools=tuple(str(d) for d in disabled),
    )


def _parse_openclaw(data: dict) -> ToolConfig | None:
    """解析 OpenClaw 的工具配置。

    tools 段包含 profile、web.search、elevated 等子项。
    如果没有 tools 段，说明没有工具配置。
    """
    tools_section = data.get("tools")
    if tools_section is None:
        return None
    profile = tools_section.get("profile", "")
    available: list[str] = []
    disabled: list[str] = []

    # web.search
    web = tools_section.get("web", {})
    search = web.get("search", {})
    if search.get("enabled", False):
        available.append("web.search")
    else:
        disabled.append("web.search")

    # elevated
    elevated = tools_section.get("elevated", {})
    if elevated.get("enabled", False):
        available.append("elevated")

    # MCP servers (from top-level mcp.servers)
    return ToolConfig(
        agent="openclaw",
        tools=tuple(available),
        disabled_tools=tuple(disabled),
        profile=profile,
    )


_PARSERS: dict[str, object] = {
    "yaml": _parse_hermes,
    "json": _parse_openclaw,
}


def scan_config(home: Path, agent: str) -> ToolConfig | None:
    """扫描指定 Agent 的工具配置，不存在则返回 None。"""
    entry = next((e for e in _CONFIG_ENTRIES if e["agent"] == agent), None)
    if entry is None:
        return None
    cfg_path = home.joinpath(*entry["path"])  # type: ignore[arg-type]
    if not cfg_path.exists():
        return None
    fmt = entry["format"]
    if fmt == "yaml":
        data = _read_yaml(cfg_path)
        return _parse_hermes(data)
    elif fmt == "json":
        data = _read_json(cfg_path)
        return _parse_openclaw(data)
    return None


def scan_all(home: Path) -> list[ToolConfig]:
    """扫描所有已安装 Agent 的工具配置。"""
    results: list[ToolConfig] = []
    for entry in _CONFIG_ENTRIES:
        cfg = scan_config(home, entry["agent"])  # type: ignore[arg-type]
        if cfg is not None:
            results.append(cfg)
    return results


def sync_tool(
    home: Path,
    target: str,
    *,
    dry_run: bool = True,
    home_override: Path | None = None,
) -> dict:
    """将 registry 中已扫描的工具配置同步到目标 Agent 配置文件。

    Parameters
    ----------
    home:
        AgentMesh registry 根目录（也用于读取源配置）。
    target:
        目标 agent 名称。
    dry_run:
        True 时只返回计划不写入。
    home_override:
        目标 agent 的 home 目录，默认与 home 相同。
    """
    actual_home = home_override or home
    cfg = scan_config(home, target)
    if cfg is None:
        return {
            "target": target,
            "dry_run": dry_run,
            "actions": [],
            "applied": 0,
            "skipped": 0,
            "error": f"未找到 {target} 的工具配置",
        }

    entry = next((e for e in _CONFIG_ENTRIES if e["agent"] == target), None)
    if entry is None:
        return {
            "target": target,
            "dry_run": dry_run,
            "actions": [],
            "applied": 0,
            "skipped": 0,
            "error": f"未知 agent: {target}",
        }

    cfg_path = actual_home.joinpath(*entry["path"])  # type: ignore[arg-type]
    actions: list[dict] = []
    applied = 0
    skipped = 0

    # 检查目标文件
    current_content = ""
    if cfg_path.exists():
        current_content = cfg_path.read_text(encoding="utf-8")

    # 重新读取源配置原始内容
    source_path = home.joinpath(*entry["path"])  # type: ignore[arg-type]
    if source_path.exists():
        source_content = source_path.read_text(encoding="utf-8")
    else:
        source_content = ""

    if current_content == source_content:
        actions.append({
            "target_path": str(cfg_path),
            "status": "skipped",
            "reason": "identical",
        })
        skipped += 1
    else:
        action_info: dict = {
            "target_path": str(cfg_path),
            "status": "would_apply" if dry_run else "applied",
            "source_path": str(source_path),
        }
        if not dry_run:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(source_content, encoding="utf-8")
            applied += 1
        actions.append(action_info)

    return {
        "target": target,
        "dry_run": dry_run,
        "actions": actions,
        "applied": applied,
        "skipped": skipped,
    }


def diff_configs(home: Path) -> list[ToolDiff]:
    """比较所有已安装 Agent 的工具配置差异。"""
    configs = scan_all(home)
    diffs: list[ToolDiff] = []
    for a, b in combinations(configs, 2):
        tools_a = set(a.tools)
        tools_b = set(b.tools)
        # tools only in a
        for t in sorted(tools_a - tools_b):
            diffs.append(
                ToolDiff(
                    type="only_in_a",
                    tool_name=t,
                    agent_a=a.agent,
                    agent_b=b.agent,
                )
            )
        # tools only in b
        for t in sorted(tools_b - tools_a):
            diffs.append(
                ToolDiff(
                    type="only_in_b",
                    tool_name=t,
                    agent_a=a.agent,
                    agent_b=b.agent,
                )
            )
        # tools disabled in one but enabled in the other
        disabled_a = set(a.disabled_tools)
        disabled_b = set(b.disabled_tools)
        for t in sorted(tools_a & disabled_b):
            diffs.append(
                ToolDiff(
                    type="enabled_in_a_disabled_in_b",
                    tool_name=t,
                    agent_a=a.agent,
                    agent_b=b.agent,
                )
            )
        for t in sorted(tools_b & disabled_a):
            diffs.append(
                ToolDiff(
                    type="enabled_in_b_disabled_in_a",
                    tool_name=t,
                    agent_a=a.agent,
                    agent_b=b.agent,
                )
            )
    return diffs
