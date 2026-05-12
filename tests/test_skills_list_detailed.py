"""Phase A4: 验证 `skills list --detailed` 的 JSON 契约与丰富字段。

工作台需要在列表页一次拿到：
- file_count / total_bytes
- source_agent / imported_at
- enabled_targets
- risk_summary
- last_diff（可选，按 --diff-targets 计算）

这些字段减少前端并行调用 `skills show` 的开销。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.config import loader
from agentmesh.config.loader import ensure_layout, resolve_agentmesh_home
from agentmesh.models.skill import NativeSkill
from agentmesh.services.registry_service import (
    describe_registry_skill_detailed,
    import_skill,
    list_registry_skills_detailed,
)
from agentmesh.services.skill_state_service import set_skill_targets


@pytest.fixture()
def fake_home_fixture(tmp_path: Path, monkeypatch):
    """Redirect user_home() so diff_skill() reads from a controlled location."""
    fake_user_home = tmp_path / "userhome"
    fake_user_home.mkdir()
    monkeypatch.setattr(loader, "user_home", lambda: fake_user_home)
    return fake_user_home


@pytest.fixture()
def registry_with_skill(tmp_path: Path, fake_home_fixture: Path):
    """Create a registry with a single imported skill plus its source tree."""
    registry = tmp_path / "agentmesh-home"
    home = resolve_agentmesh_home(str(registry))
    ensure_layout(home)

    source = tmp_path / "source-skill" / "demo-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill for Phase A4.\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    (source / "scripts").mkdir()
    (source / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")

    native = NativeSkill(
        name="demo-skill",
        description="Demo skill for Phase A4.",
        agent="hermes",
        source_path=source,
        entrypoint=source / "SKILL.md",
        digest="digest-demo-skill",
    )
    import_skill(home, native)
    return home


def test_describe_detailed_returns_enriched_fields(registry_with_skill: Path):
    detail = describe_registry_skill_detailed(registry_with_skill, "demo-skill")

    skill = detail["skill"]
    assert skill["name"] == "demo-skill"
    # 原 describe_registry_skill 字段保留
    assert skill["files"]["total"] >= 2
    # 新增字段
    assert skill["file_count"] == skill["files"]["total"]
    assert skill["total_bytes"] > 0
    assert skill["source_agent"] == "hermes"
    assert skill["imported_at"]  # ISO timestamp

    assert detail["enabled_targets"] == []
    assert detail["last_diff"] == {}
    assert "risk_summary" in detail


def test_describe_detailed_reflects_enable_state(registry_with_skill: Path):
    set_skill_targets(registry_with_skill, "demo-skill", "hermes,openclaw", enabled=True)

    detail = describe_registry_skill_detailed(registry_with_skill, "demo-skill")
    assert detail["enabled_targets"] == ["hermes", "openclaw"]


def test_describe_detailed_with_diff_targets_computes_levels(
    registry_with_skill: Path, fake_home_fixture: Path
):
    """When --diff-targets is provided, each target produces a conflict level name."""
    detail = describe_registry_skill_detailed(
        registry_with_skill,
        "demo-skill",
        with_diff_targets=["hermes", "openclaw"],
    )
    assert set(detail["last_diff"]) == {"hermes", "openclaw"}
    # 目标 runtime 未安装时 diff_engine 会返回 STRUCTURE_CHANGED（目标不存在）
    for level in detail["last_diff"].values():
        assert isinstance(level, str)
        assert level != ""


def test_describe_detailed_ignores_unknown_diff_target(registry_with_skill: Path):
    """未在 AGENT_TARGETS 中的目标应被优雅跳过，不应抛异常。"""
    detail = describe_registry_skill_detailed(
        registry_with_skill,
        "demo-skill",
        with_diff_targets=["unknown-target"],
    )
    assert detail["last_diff"] == {}


def test_list_registry_skills_detailed_returns_all(registry_with_skill: Path):
    items = list_registry_skills_detailed(registry_with_skill)
    assert len(items) == 1
    assert items[0]["skill"]["name"] == "demo-skill"
    assert "file_count" in items[0]["skill"]
    assert "enabled_targets" in items[0]


def test_cli_skills_list_detailed_json_envelope(registry_with_skill: Path, fake_home_fixture: Path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "skills",
            "list",
            "--registry",
            str(registry_with_skill),
            "--detailed",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.skills-list/v1"
    assert payload["command"] == "skills list"
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["detailed"] is True
    assert data["diff_targets"] == []
    assert data["duplicates"] == {}
    assert data["conflicts"] == []
    assert len(data["skills"]) == 1
    item = data["skills"][0]
    assert item["skill"]["name"] == "demo-skill"
    assert item["skill"]["file_count"] >= 2
    assert item["skill"]["total_bytes"] > 0
    assert item["skill"]["source_agent"] == "hermes"
    assert item["skill"]["imported_at"]
    assert item["enabled_targets"] == []
    assert item["last_diff"] == {}
    assert item["risk_summary"]["findings"] >= 0


def test_cli_skills_list_detailed_with_diff_targets(
    registry_with_skill: Path, fake_home_fixture: Path
):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "skills",
            "list",
            "--registry",
            str(registry_with_skill),
            "--detailed",
            "--diff-targets",
            "hermes,openclaw",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    data = payload["data"]
    assert data["diff_targets"] == ["hermes", "openclaw"]
    item = data["skills"][0]
    assert set(item["last_diff"]) == {"hermes", "openclaw"}


def test_cli_skills_list_non_detailed_preserves_legacy_shape(
    registry_with_skill: Path, fake_home_fixture: Path
):
    """不带 --detailed 时保持旧契约（只有 name 数组），避免破坏现有消费者。"""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "skills",
            "list",
            "--registry",
            str(registry_with_skill),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    data = payload["data"]
    assert data["skills"] == ["demo-skill"]
    assert data["duplicates"] == {}
    assert data["conflicts"] == []
    # 旧契约不包含 detailed / diff_targets 键
    assert "detailed" not in data
    assert "diff_targets" not in data


def test_cli_skills_list_detailed_human_output(registry_with_skill: Path, fake_home_fixture: Path):
    """不加 --json 时输出核心列表行，便于终端阅读。"""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "skills",
            "list",
            "--registry",
            str(registry_with_skill),
            "--detailed",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "demo-skill" in result.output
    assert "files=" in result.output
    assert "bytes=" in result.output
    assert "source=hermes" in result.output


def test_cli_skills_list_detailed_shows_enabled_targets(
    registry_with_skill: Path, fake_home_fixture: Path
):
    set_skill_targets(registry_with_skill, "demo-skill", "hermes,openclaw", enabled=True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "skills",
            "list",
            "--registry",
            str(registry_with_skill),
            "--detailed",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    item = payload["data"]["skills"][0]
    assert item["enabled_targets"] == ["hermes", "openclaw"]
