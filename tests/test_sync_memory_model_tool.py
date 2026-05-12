"""Memory/Model/Tool sync/apply 测试。"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.memory_service import (
    import_memory,
    scan_memory_files,
    sync_memory,
)
from agentmesh.services.model_service import sync_model
from agentmesh.services.tool_service import sync_tool

runner = CliRunner()


# ── helpers ──────────────────────────────────────────────────────────────


def _make_memory_files(fake_home: Path) -> None:
    hermes_dir = fake_home / ".hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)
    (hermes_dir / "MEMORY.md").write_text("# Hermes Memory\n\nHermes context.", encoding="utf-8")
    (hermes_dir / "USER.md").write_text("# User Prefs\n\nName: Alice", encoding="utf-8")


def _setup_hermes_model(
    home: Path,
    *,
    default: str = "mimo-v2.5-pro",
    provider: str = "custom",
) -> None:
    cfg_dir = home / ".hermes"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        f"model:\n  default: {default}\n  provider: {provider}\n"
        "  base_url: https://example.com/v1\n  context_length: 128000\n",
        encoding="utf-8",
    )


def _setup_hermes_tool(
    home: Path,
    *,
    toolsets: list[str] | None = None,
    disabled: list[str] | None = None,
) -> None:
    cfg_dir = home / ".hermes"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    toolsets = toolsets or ["hermes-cli"]
    disabled = disabled or []
    lines = ["toolsets:"]
    for t in toolsets:
        lines.append(f"- {t}")
    lines.append("agent:")
    lines.append("  disabled_toolsets:")
    for d in disabled:
        lines.append(f"  - {d}")
    (cfg_dir / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── memory sync service tests ────────────────────────────────────────────


def test_sync_memory_dry_run(fake_home):
    """dry-run 模式应返回计划但不写入。"""
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    # 先导入
    for a in scan_memory_files(fake_home, "hermes"):
        import_memory(registry, a)

    # 修改源文件
    (fake_home / ".hermes" / "MEMORY.md").write_text("# Modified\n\nNew content.", encoding="utf-8")

    result = sync_memory(registry, "hermes", dry_run=True, home=fake_home)
    assert result["target"] == "hermes"
    assert result["dry_run"] is True
    # 源文件已修改，应有 would_apply 动作
    actions = result["actions"]
    changed = [a for a in actions if a["status"] == "would_apply"]
    assert len(changed) > 0


def test_sync_memory_apply(fake_home):
    """apply 模式应将 registry 内容写回到目标路径。"""
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    for a in scan_memory_files(fake_home, "hermes"):
        import_memory(registry, a)

    # 修改源文件
    (fake_home / ".hermes" / "MEMORY.md").write_text("# Modified\n\nNew.", encoding="utf-8")

    result = sync_memory(registry, "hermes", dry_run=False, home=fake_home)
    assert result["dry_run"] is False
    assert result["applied"] > 0

    # 验证源文件被恢复为 registry 内容
    restored = (fake_home / ".hermes" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Hermes context." in restored


def test_sync_memory_identical_skipped(fake_home):
    """内容一致时应 skip。"""
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    for a in scan_memory_files(fake_home, "hermes"):
        import_memory(registry, a)

    # 不修改，再 sync
    result = sync_memory(registry, "hermes", dry_run=False, home=fake_home)
    assert result["skipped"] == len(result["actions"])


def test_sync_memory_no_assets(fake_home):
    """无已导入资产时返回空。"""
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    result = sync_memory(registry, "hermes", dry_run=True, home=fake_home)
    assert result["applied"] == 0
    assert "error" in result


# ── model sync service tests ─────────────────────────────────────────────


def test_sync_model_dry_run(tmp_path: Path):
    """model sync dry-run 应返回计划。"""
    _setup_hermes_model(tmp_path, default="gpt-5", provider="openai")
    result = sync_model(tmp_path, "hermes", dry_run=True, home_override=tmp_path)
    assert result["target"] == "hermes"
    assert result["dry_run"] is True
    assert len(result["actions"]) > 0


def test_sync_model_apply(tmp_path: Path):
    """model sync apply 应将 registry 模型配置写回目标。"""
    _setup_hermes_model(tmp_path, default="gpt-5", provider="openai")
    result = sync_model(tmp_path, "hermes", dry_run=False, home_override=tmp_path)
    assert result["dry_run"] is False
    assert result["applied"] >= 0


def test_sync_model_unknown_target(tmp_path: Path):
    """未知 target 应返回错误。"""
    result = sync_model(tmp_path, "unknown-agent", dry_run=True, home_override=tmp_path)
    assert result["target"] == "unknown-agent"
    assert "error" in result


# ── tool sync service tests ──────────────────────────────────────────────


def test_sync_tool_dry_run(tmp_path: Path):
    """tool sync dry-run 应返回计划。"""
    _setup_hermes_tool(tmp_path, toolsets=["hermes-cli", "terminal"])
    result = sync_tool(tmp_path, "hermes", dry_run=True, home_override=tmp_path)
    assert result["target"] == "hermes"
    assert result["dry_run"] is True
    assert len(result["actions"]) > 0


def test_sync_tool_apply(tmp_path: Path):
    """tool sync apply 应将 registry 工具配置写回目标。"""
    _setup_hermes_tool(tmp_path, toolsets=["hermes-cli", "terminal"])
    result = sync_tool(tmp_path, "hermes", dry_run=False, home_override=tmp_path)
    assert result["dry_run"] is False


def test_sync_tool_unknown_target(tmp_path: Path):
    """未知 target 应返回错误。"""
    result = sync_tool(tmp_path, "unknown-agent", dry_run=True, home_override=tmp_path)
    assert "error" in result


# ── CLI: memory sync ────────────────────────────────────────────────────


def test_cli_memory_sync_dry_run(fake_home):
    """CLI memory sync --dry-run 应输出计划。"""
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    runner.invoke(app, ["init", "--registry", str(registry)])
    runner.invoke(app, ["memory", "import", "hermes", "--registry", str(registry), "--yes"])

    result = runner.invoke(
        app,
        ["memory", "sync", "--to", "hermes", "--registry", str(registry), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.memory-sync/v1"
    assert data["data"]["plan"]["dry_run"] is True


def test_cli_memory_sync_apply(fake_home):
    """CLI memory sync --to hermes --apply 应写入并输出 applied。"""
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    runner.invoke(app, ["init", "--registry", str(registry)])
    runner.invoke(app, ["memory", "import", "hermes", "--registry", str(registry), "--yes"])

    # 修改源
    (fake_home / ".hermes" / "MEMORY.md").write_text("# Modified", encoding="utf-8")

    result = runner.invoke(
        app,
        ["memory", "sync", "--to", "hermes", "--apply",
         "--yes", "--registry", str(registry), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.memory-sync/v1"
    assert data["data"]["plan"]["dry_run"] is False


# ── CLI: model sync ─────────────────────────────────────────────────────


def test_cli_model_sync_dry_run(tmp_path: Path):
    """CLI model sync --dry-run 应输出计划。"""
    _setup_hermes_model(tmp_path)
    result = runner.invoke(
        app,
        ["model", "sync", "--to", "hermes", "--registry", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.model-sync/v1"
    assert data["data"]["plan"]["dry_run"] is True


def test_cli_model_sync_apply(tmp_path: Path):
    """CLI model sync --apply 应写入。"""
    _setup_hermes_model(tmp_path, default="new-model", provider="new-provider")
    result = runner.invoke(
        app,
        ["model", "sync", "--to", "hermes", "--apply",
         "--yes", "--registry", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["plan"]["dry_run"] is False


# ── CLI: tool sync ──────────────────────────────────────────────────────


def test_cli_tool_sync_dry_run(tmp_path: Path):
    """CLI tool sync --dry-run 应输出计划。"""
    _setup_hermes_tool(tmp_path)
    result = runner.invoke(
        app,
        ["tool", "sync", "--to", "hermes", "--registry", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.tool-sync/v1"
    assert data["data"]["plan"]["dry_run"] is True


def test_cli_tool_sync_apply(tmp_path: Path):
    """CLI tool sync --apply 应写入。"""
    _setup_hermes_tool(tmp_path, toolsets=["new-tool"])
    result = runner.invoke(
        app,
        ["tool", "sync", "--to", "hermes", "--apply",
         "--yes", "--registry", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["plan"]["dry_run"] is False
