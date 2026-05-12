"""PromptMesh M7 测试：版本管理、多 target 同步、冲突解决。"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.prompt_service import (
    PromptError,
    add_prompt,
    enable_prompt,
    enable_prompt_multi,
    list_prompt_versions,
    update_prompt,
)

# ── 版本管理 ──────────────────────────────────────────────────────────


def test_update_prompt_creates_new_version(fake_home):
    """更新 prompt 应产生新版本，旧内容保留在版本历史中。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "review", "Review Prompt", "# v1 content\n")

    result = update_prompt(registry, "review", content="# v2 content\n")

    assert result["version"] == 2
    assert result["content_hash"] != ""

    # 验证版本历史
    versions = list_prompt_versions(registry, "review")
    assert len(versions) == 2
    assert versions[0]["version"] == 1
    assert versions[1]["version"] == 2


def test_update_prompt_preserves_name_and_description(fake_home):
    """不传新 name/description 时保留原有值。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo", "Demo", "# v1\n", description="原始描述")

    result = update_prompt(registry, "demo", content="# v2\n")

    assert result["name"] == "Demo"
    assert result["description"] == "原始描述"
    assert result["version"] == 2


def test_update_prompt_with_new_name(fake_home):
    """传新 name 时应更新。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo", "Old Name", "# v1\n")

    result = update_prompt(registry, "demo", content="# v2\n", name="New Name")

    assert result["name"] == "New Name"
    assert result["version"] == 2


def test_update_prompt_not_found(fake_home):
    """更新不存在的 prompt 应抛出 PromptError。"""
    registry = fake_home / "agentmesh"
    with pytest.raises(PromptError, match="不存在"):
        update_prompt(registry, "nonexistent", content="# x\n")


def test_update_prompt_no_changes_is_noop(fake_home):
    """内容完全相同时应抛出异常或返回无变化标记。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo", "Demo", "# same\n")
    with pytest.raises(PromptError, match="无变更"):
        update_prompt(registry, "demo", content="# same\n")


# ── 多 target 同步 ───────────────────────────────────────────────────


def test_enable_prompt_multi_dry_run(fake_home):
    """dry-run 模式下多 target 同步应返回每个 target 的计划。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "shared", "Shared", "# shared prompt\n")

    plans = enable_prompt_multi(
        registry, "shared", ["codex", "claude-code"], apply=False, home=fake_home
    )

    assert len(plans) == 2
    assert plans[0]["target"] == "codex"
    assert plans[1]["target"] == "claude-code"
    for p in plans:
        assert p["apply"] is False
        assert p["will_write"] is False


def test_enable_prompt_multi_apply(fake_home):
    """apply 模式下多 target 应写入所有目标。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "shared", "Shared", "# shared prompt\n")

    plans = enable_prompt_multi(
        registry, "shared", ["codex", "claude-code"], apply=True, home=fake_home
    )

    assert len(plans) == 2
    for p in plans:
        assert p["apply"] is True
        assert p["will_write"] is True

    # 验证文件确实被写入
    assert (fake_home / ".codex" / "AGENTS.md").read_text() == "# shared prompt\n"
    assert (fake_home / ".claude" / "CLAUDE.md").read_text() == "# shared prompt\n"


def test_enable_prompt_multi_unknown_target_error(fake_home):
    """包含未知 target 时应抛出 PromptError。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "shared", "Shared", "# content\n")

    with pytest.raises(PromptError, match="暂不支持"):
        enable_prompt_multi(
            registry, "shared", ["codex", "bad-target"], apply=False, home=fake_home
        )


def test_enable_prompt_multi_empty_targets_is_noop(fake_home):
    """空 targets 列表应返回空结果。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "shared", "Shared", "# content\n")

    plans = enable_prompt_multi(registry, "shared", [], apply=False, home=fake_home)
    assert plans == []


# ── 冲突解决 ─────────────────────────────────────────────────────────


def test_enable_prompt_detects_conflict_when_live_differs(fake_home):
    """当 target 已有不同内容时，应报告冲突。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# new prompt\n")
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# existing content\n", encoding="utf-8")

    plan = enable_prompt(registry, "new", "codex", apply=False, home=fake_home)

    assert plan["conflict"] is True
    assert plan["conflict_level"] in ("content_changed", "unmanaged")


def test_enable_prompt_no_conflict_when_live_missing(fake_home):
    """live 文件不存在时无冲突。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# new prompt\n")

    plan = enable_prompt(registry, "new", "codex", apply=False, home=fake_home)

    assert plan.get("conflict", False) is False


def test_enable_prompt_no_conflict_when_live_identical(fake_home):
    """live 内容与 prompt 相同时无冲突。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# same\n")
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# same\n", encoding="utf-8")

    plan = enable_prompt(registry, "new", "codex", apply=False, home=fake_home)

    assert plan.get("conflict", False) is False


def test_enable_prompt_conflict_strategy_skip(fake_home):
    """冲突时使用 skip 策略应不写入。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# new\n")
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# existing\n", encoding="utf-8")

    plan = enable_prompt(
        registry,
        "new",
        "codex",
        apply=True,
        home=fake_home,
        conflict_strategy="skip",
    )

    assert plan["skipped"] is True
    assert live_file.read_text() == "# existing\n"


def test_enable_prompt_conflict_strategy_force(fake_home):
    """冲突时使用 force 策略应强制覆盖（不创建 snapshot）。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# new\n")
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# existing\n", encoding="utf-8")

    plan = enable_prompt(
        registry,
        "new",
        "codex",
        apply=True,
        home=fake_home,
        conflict_strategy="force",
    )

    assert plan["skipped"] is False
    assert live_file.read_text() == "# new\n"
    # force 模式不创建 snapshot
    assert plan["snapshot"] is None


def test_enable_prompt_conflict_strategy_backup_is_default(fake_home):
    """默认 backup 策略：冲突时备份旧内容再覆盖。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# new\n")
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# existing\n", encoding="utf-8")

    plan = enable_prompt(registry, "new", "codex", apply=True, home=fake_home)

    assert plan["skipped"] is False
    assert live_file.read_text() == "# new\n"
    assert plan["snapshot"] is not None


def test_enable_prompt_conflict_dry_run_with_skip_strategy(fake_home):
    """dry-run + skip 策略：应标记 conflict 但不写入。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# new\n")
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# existing\n", encoding="utf-8")

    plan = enable_prompt(
        registry,
        "new",
        "codex",
        apply=False,
        home=fake_home,
        conflict_strategy="skip",
    )

    assert plan["conflict"] is True
    assert plan["skipped"] is False  # dry-run 不实际 skip
    assert live_file.read_text() == "# existing\n"


# ── 多 target + 冲突 ─────────────────────────────────────────────────


def test_enable_prompt_multi_with_conflict_strategy(fake_home):
    """多 target 同步时应传递冲突策略。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "shared", "Shared", "# shared\n")

    # 预置一个 target 已有不同内容
    codex_file = fake_home / ".codex" / "AGENTS.md"
    codex_file.parent.mkdir(parents=True)
    codex_file.write_text("# existing codex\n", encoding="utf-8")

    plans = enable_prompt_multi(
        registry,
        "shared",
        ["codex", "claude-code"],
        apply=True,
        home=fake_home,
        conflict_strategy="skip",
    )

    # codex 应被 skip
    assert plans[0]["skipped"] is True
    assert codex_file.read_text() == "# existing codex\n"
    # claude-code 应正常写入
    assert plans[1]["skipped"] is False
    assert (fake_home / ".claude" / "CLAUDE.md").read_text() == "# shared\n"


# ── CLI 集成 ─────────────────────────────────────────────────────────


def test_cli_prompts_update_dry_run(fake_home):
    """CLI prompts update --dry-run 应返回版本信息。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo", "Demo", "# v1\n")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "prompts",
            "update",
            "demo",
            "--content-file",
            str(_write_tmp(fake_home, "v2.md", "# v2\n")),
            "--registry",
            str(registry),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["version"] == 2


def test_cli_prompts_versions(fake_home):
    """CLI prompts versions 应列出所有版本。"""
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo", "Demo", "# v1\n")
    update_prompt(registry, "demo", content="# v2\n")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["prompts", "versions", "demo", "--registry", str(registry), "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data["data"]["versions"]) == 2


def test_cli_prompts_enable_multi_targets(fake_home, monkeypatch):
    """CLI prompts enable --targets codex,claude-code 应同步多个 target。"""
    monkeypatch.setattr("agentmesh.config.loader.user_home", lambda: fake_home)
    registry = fake_home / "agentmesh"
    add_prompt(registry, "shared", "Shared", "# shared\n")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "prompts",
            "enable",
            "shared",
            "--targets",
            "codex,claude-code",
            "--registry",
            str(registry),
            "--apply",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data["data"]["plans"]) == 2
    assert (fake_home / ".codex" / "AGENTS.md").exists()
    assert (fake_home / ".claude" / "CLAUDE.md").exists()


def test_cli_prompts_enable_conflict_strategy_skip(fake_home, monkeypatch):
    """CLI prompts enable --conflict-strategy skip 应跳过冲突。"""
    monkeypatch.setattr("agentmesh.config.loader.user_home", lambda: fake_home)
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new", "New", "# new\n")
    codex_file = fake_home / ".codex" / "AGENTS.md"
    codex_file.parent.mkdir(parents=True)
    codex_file.write_text("# existing\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "prompts",
            "enable",
            "new",
            "--target",
            "codex",
            "--conflict-strategy",
            "skip",
            "--registry",
            str(registry),
            "--apply",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["plan"]["skipped"] is True
    assert codex_file.read_text() == "# existing\n"


# ── helper ───────────────────────────────────────────────────────────


def _write_tmp(fake_home, name, content):
    p = fake_home / name
    p.write_text(content, encoding="utf-8")
    return p
