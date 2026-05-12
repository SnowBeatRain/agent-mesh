"""ModelMesh 服务：扫描和比较各 Agent 的模型配置。"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from ruamel.yaml import YAML

from agentmesh.models.model_config import ModelConfig, ModelDiff

_yaml = YAML(typ="safe")

# 各 Agent 模型配置的路径和解析逻辑
_CONFIG_ENTRIES: list[dict[str, object]] = [
    {
        "agent": "hermes",
        "path": (".hermes", "config.yaml"),
        "format": "yaml",
    },
    {
        "agent": "openclaw",
        "path": (".openclaw", "openclaw.json"),
        "format": "openclaw-json",
    },
    {
        "agent": "codex",
        "path": (".codex", "config.json"),
        "format": "json",
    },
    {
        "agent": "claude-code",
        "path": (".claude", "settings.json"),
        "format": "json",
    },
]

# 要进行 diff 比较的字段
_DIFF_FIELDS = ("default_model", "provider")


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return _yaml.load(f) or {}


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_hermes(data: dict) -> ModelConfig:
    model_section = data.get("model", {})
    return ModelConfig(
        agent="hermes",
        default_model=model_section.get("default", ""),
        provider=model_section.get("provider", ""),
        base_url=model_section.get("base_url", ""),
        context_length=model_section.get("context_length"),
    )


def _parse_openclaw(data: dict) -> ModelConfig:
    models_section = data.get("models", {})
    providers = models_section.get("providers", {})
    available: list[str] = []
    first_model = ""
    for _prov_name, prov_data in providers.items():
        for m in prov_data.get("models", []):
            mid = m.get("id", "")
            if mid:
                available.append(mid)
                if not first_model:
                    first_model = mid
    return ModelConfig(
        agent="openclaw",
        default_model=first_model,
        provider="openclaw",
        available_models=tuple(available),
    )


def _parse_json_simple(data: dict, agent: str) -> ModelConfig:
    return ModelConfig(
        agent=agent,
        default_model=data.get("model", ""),
    )


_PARSERS: dict[str, object] = {
    "yaml": _parse_hermes,
    "openclaw-json": _parse_openclaw,
    "json": _parse_json_simple,
}


def scan_config(home: Path, agent: str) -> ModelConfig | None:
    """扫描指定 Agent 的模型配置，不存在则返回 None。"""
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
    elif fmt == "openclaw-json":
        data = _read_json(cfg_path)
        return _parse_openclaw(data)
    elif fmt == "json":
        data = _read_json(cfg_path)
        return _parse_json_simple(data, agent)
    return None


def scan_all(home: Path) -> list[ModelConfig]:
    """扫描所有已安装 Agent 的模型配置。"""
    results: list[ModelConfig] = []
    for entry in _CONFIG_ENTRIES:
        cfg = scan_config(home, entry["agent"])  # type: ignore[arg-type]
        if cfg is not None:
            results.append(cfg)
    return results


def sync_model(
    home: Path,
    target: str,
    *,
    dry_run: bool = True,
    home_override: Path | None = None,
) -> dict:
    """将 registry 中已扫描的模型配置同步到目标 Agent 配置文件。

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
            "error": f"未找到 {target} 的模型配置",
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
    target_exists = cfg_path.exists()
    current_content = ""
    if target_exists:
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


def diff_configs(home: Path) -> list[ModelDiff]:
    """比较所有已安装 Agent 的模型配置差异。"""
    configs = scan_all(home)
    diffs: list[ModelDiff] = []
    for a, b in combinations(configs, 2):
        for field_name in _DIFF_FIELDS:
            val_a = getattr(a, field_name, None)
            val_b = getattr(b, field_name, None)
            if val_a and val_b and val_a != val_b:
                diffs.append(
                    ModelDiff(
                        field=field_name,
                        agent_a=a.agent,
                        value_a=val_a,
                        agent_b=b.agent,
                        value_b=val_b,
                    )
                )
    return diffs
