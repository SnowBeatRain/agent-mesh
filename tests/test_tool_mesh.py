"""ToolMesh 探索：工具配置 scan / diff / list 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.models.tool_config import ToolConfig, ToolDiff
from agentmesh.services.tool_service import diff_configs, scan_all, scan_config

runner = CliRunner()


# ── helpers ──────────────────────────────────────────────────────────────


def _setup_hermes(
    home: Path,
    *,
    toolsets: list[str] | None = None,
    disabled: list[str] | None = None,
) -> None:
    cfg_dir = home / ".hermes"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    toolsets = toolsets or ["hermes-cli"]
    disabled = disabled or []
    lines = [
        "toolsets:",
    ]
    for t in toolsets:
        lines.append(f"- {t}")
    lines.append("agent:")
    lines.append("  disabled_toolsets:")
    for d in disabled:
        lines.append(f"  - {d}")
    (cfg_dir / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _setup_openclaw(
    home: Path,
    *,
    profile: str = "coding",
    web_search: bool = True,
    elevated: bool = True,
) -> None:
    cfg_dir = home / ".openclaw"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    tools: dict = {
        "profile": profile,
        "web": {"search": {"enabled": web_search}},
        "elevated": {"enabled": elevated},
    }
    data = {"tools": tools}
    (cfg_dir / "openclaw.json").write_text(json.dumps(data), encoding="utf-8")


def _setup_claude_code(home: Path) -> None:
    cfg_dir = home / ".claude"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "settings.json").write_text(
        json.dumps({"model": "opus[1m]"}), encoding="utf-8"
    )


def _setup_codex(home: Path) -> None:
    cfg_dir = home / ".codex"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"model": "o3-mini"}), encoding="utf-8"
    )


# ── ToolConfig dataclass ───────────────────────────────────────────────


def test_tool_config_schema_fields():
    cfg = ToolConfig(
        agent="hermes",
        tools=("terminal", "file", "web"),
        disabled_tools=("sandbox",),
    )
    assert cfg.agent == "hermes"
    assert cfg.tools == ("terminal", "file", "web")
    assert cfg.disabled_tools == ("sandbox",)
    assert cfg.schema == "agentmesh.tool-config/v1"


def test_tool_config_to_dict():
    cfg = ToolConfig(
        agent="hermes",
        tools=("terminal", "file"),
        disabled_tools=(),
        profile="coding",
        mcp_servers=("hermes",),
    )
    d = cfg.to_dict()
    assert d["schema"] == "agentmesh.tool-config/v1"
    assert d["agent"] == "hermes"
    assert d["tools"] == ["terminal", "file"]
    assert d["disabled_tools"] == []
    assert d["profile"] == "coding"
    assert d["mcp_servers"] == ["hermes"]
    assert isinstance(d["tools"], list)


def test_tool_config_defaults():
    cfg = ToolConfig(agent="test")
    assert cfg.tools == ()
    assert cfg.disabled_tools == ()
    assert cfg.profile == ""
    assert cfg.mcp_servers == ()


# ── scan ─────────────────────────────────────────────────────────────────


def test_scan_hermes_config(tmp_path: Path):
    _setup_hermes(tmp_path, toolsets=["hermes-cli"], disabled=["sandbox"])
    cfg = scan_config(tmp_path, "hermes")
    assert cfg is not None
    assert cfg.agent == "hermes"
    assert "hermes-cli" in cfg.tools
    assert "sandbox" in cfg.disabled_tools


def test_scan_hermes_multiple_toolsets(tmp_path: Path):
    _setup_hermes(tmp_path, toolsets=["hermes-cli", "terminal", "file"])
    cfg = scan_config(tmp_path, "hermes")
    assert cfg is not None
    assert len(cfg.tools) == 3
    assert "terminal" in cfg.tools


def test_scan_openclaw_config(tmp_path: Path):
    _setup_openclaw(tmp_path, profile="coding", web_search=True, elevated=True)
    cfg = scan_config(tmp_path, "openclaw")
    assert cfg is not None
    assert cfg.agent == "openclaw"
    assert cfg.profile == "coding"
    assert "web.search" in cfg.tools
    assert "elevated" in cfg.tools


def test_scan_openclaw_disabled_tools(tmp_path: Path):
    _setup_openclaw(tmp_path, profile="coding", web_search=False, elevated=False)
    cfg = scan_config(tmp_path, "openclaw")
    assert cfg is not None
    assert cfg.profile == "coding"
    assert "web.search" not in cfg.tools
    assert "elevated" not in cfg.tools


def test_scan_claude_code_config(tmp_path: Path):
    _setup_claude_code(tmp_path)
    cfg = scan_config(tmp_path, "claude-code")
    # claude-code settings.json doesn't have explicit tool section
    # scan should return a minimal config or None
    assert cfg is None


def test_scan_codex_config(tmp_path: Path):
    _setup_codex(tmp_path)
    cfg = scan_config(tmp_path, "codex")
    assert cfg is None


def test_scan_missing_config_returns_none(tmp_path: Path):
    cfg = scan_config(tmp_path, "hermes")
    assert cfg is None


def test_scan_all_returns_installed_configs(tmp_path: Path):
    _setup_hermes(tmp_path)
    _setup_openclaw(tmp_path)
    _setup_claude_code(tmp_path)
    results = scan_all(tmp_path)
    names = {c.agent for c in results}
    assert "hermes" in names
    assert "openclaw" in names
    assert "claude-code" not in names  # no tool section


# ── diff ─────────────────────────────────────────────────────────────────


def test_diff_same_tools(tmp_path: Path):
    _setup_hermes(tmp_path, toolsets=["hermes-cli"])
    _setup_openclaw(tmp_path, profile="default")
    diffs = diff_configs(tmp_path)
    # no meaningful shared fields to diff
    assert isinstance(diffs, list)


def test_diff_different_profiles(tmp_path: Path):
    _setup_hermes(tmp_path, toolsets=["hermes-cli"])
    _setup_openclaw(tmp_path, profile="coding")
    diffs = diff_configs(tmp_path)
    # profile is per-agent, not directly comparable across agents
    # but tools overlap should be detected
    assert isinstance(diffs, list)


def test_diff_tool_overlap(tmp_path: Path):
    _setup_hermes(tmp_path, toolsets=["hermes-cli", "terminal"])
    _setup_openclaw(tmp_path, profile="coding", web_search=True)
    diffs = diff_configs(tmp_path)
    # both have tools, some may overlap or differ
    assert isinstance(diffs, list)


def test_diff_only_installed_agents(tmp_path: Path):
    _setup_hermes(tmp_path)
    diffs = diff_configs(tmp_path)
    assert len(diffs) == 0  # only 1 agent → no pairs


def test_tool_diff_dataclass():
    d = ToolDiff(
        type="only_in_a",
        tool_name="terminal",
        agent_a="hermes",
        agent_b="openclaw",
    )
    assert d.type == "only_in_a"
    d2 = d.to_dict()
    assert d2["tool_name"] == "terminal"
    assert d2["agent_a"] == "hermes"


# ── CLI: am tool scan ──────────────────────────────────────────────────


def test_tool_scan_json(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path)
    _setup_openclaw(tmp_path)
    result = runner.invoke(app, ["tool", "scan", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.tool-scan/v1"
    assert payload["command"] == "tool scan"
    assert payload["status"] == "ok"
    configs = payload["data"]["configs"]
    names = {c["agent"] for c in configs}
    assert "hermes" in names
    assert "openclaw" in names


def test_tool_scan_human_readable(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path)
    result = runner.invoke(app, ["tool", "scan", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "hermes" in result.output


# ── CLI: am tool diff ──────────────────────────────────────────────────


def test_tool_diff_json(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path, toolsets=["hermes-cli", "terminal"])
    _setup_openclaw(tmp_path, profile="coding", web_search=True)
    result = runner.invoke(app, ["tool", "diff", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.tool-diff/v1"
    assert payload["command"] == "tool diff"


def test_tool_diff_no_configs(tmp_path: Path, monkeypatch):
    result = runner.invoke(app, ["tool", "diff", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["diffs"] == []


# ── CLI: am tool list ──────────────────────────────────────────────────


def test_tool_list_json(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path)
    _setup_openclaw(tmp_path)
    result = runner.invoke(app, ["tool", "list", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.tool-list/v1"
    agents = payload["data"]["agents"]
    assert len(agents) == 2
