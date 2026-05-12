from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.sync_service import sync


def make_registry_skill(registry: Path, name: str, body: str = "# Demo\n") -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    return skill


def make_runtime_skill(home: Path, name: str, body: str = "# Demo\n") -> Path:
    skill = home / ".hermes" / "skills" / "custom" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    return skill


def test_dry_run_sync_plan_includes_diff_policy_and_blocked_reasons(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "same-skill")
    make_registry_skill(registry, "changed-skill", "# Registry\n")
    make_registry_skill(registry, "unsafe-skill", "token = SHOULD_NOT_LEAK\n")
    make_runtime_skill(fake_home, "same-skill")
    make_runtime_skill(fake_home, "changed-skill", "# Target\n")

    plan = sync(registry, ["hermes"], apply=False)

    assert plan["mode"] == "DRY-RUN"
    assert plan["summary"] == {
        "actions": 3,
        "allowed": 1,
        "blocked": 2,
        "warnings": 0,
    }
    actions = {item["skill"]: item for item in plan["actions"]}

    assert actions["same-skill"]["decision"] == "allow"
    assert actions["same-skill"]["diff"]["name"] == "IDENTICAL"
    assert actions["same-skill"]["policy"]["allowed"] is True
    assert actions["same-skill"]["blocked_reasons"] == []

    assert actions["changed-skill"]["decision"] == "block"
    assert actions["changed-skill"]["diff"]["name"] == "CONTENT_CHANGED"
    assert actions["changed-skill"]["blocked_reasons"] == ["conflict:CONTENT_CHANGED"]

    assert actions["unsafe-skill"]["decision"] == "block"
    assert actions["unsafe-skill"]["diff"]["name"] == "STRUCTURE_CHANGED"
    assert actions["unsafe-skill"]["policy"]["allowed"] is False
    assert "policy:block" in actions["unsafe-skill"]["blocked_reasons"]
    assert "SHOULD_NOT_LEAK" not in json.dumps(plan, ensure_ascii=False)
    assert "<redacted>" in json.dumps(plan, ensure_ascii=False)


def test_sync_cli_json_contains_rendered_plan_envelope(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill")
    make_runtime_skill(fake_home, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "sync", "--registry", str(registry), "--to", "hermes", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-sync/v1"
    assert data["command"] == "skills sync"
    assert data["status"] == "planned"
    assert data["dry_run"] is True
    plan = data["data"]["plan"]
    assert plan["sync_mode"] == "copy"
    assert plan["summary"]["actions"] == 1
    assert plan["actions"][0]["diff"]["name"] == "IDENTICAL"
    assert plan["actions"][0]["policy"]["allowed"] is True


def test_sync_symlink_apply_requires_confirm_without_traceback(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "sync",
            "--registry",
            str(registry),
            "--to",
            "hermes",
            "--mode",
            "symlink",
            "--apply",
        ],
    )

    assert result.exit_code != 0
    assert "symlink 模式需要显式 --confirm" in result.output
    assert "Traceback" not in result.output


def test_sync_symlink_apply_with_confirm_creates_link_when_supported(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "sync",
            "--registry",
            str(registry),
            "--to",
            "hermes",
            "--mode",
            "symlink",
            "--apply",
            "--confirm",
        ],
    )

    if result.exit_code != 0 and "symlink failed" in result.output:
        pytest.skip(result.output)
    assert result.exit_code == 0, result.output
    target = fake_home / ".hermes" / "skills" / "custom" / "demo-skill"
    assert target.is_symlink()
    assert target.resolve() == (registry / "skills" / "demo-skill").resolve()
    assert (target.parent / ".demo-skill.agentmesh-link.yaml").exists()
    assert "Traceback" not in result.output


def test_sync_rejects_dry_run_and_apply_together_without_traceback(tmp_path):
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "sync",
            "--registry",
            str(registry),
            "--to",
            "hermes",
            "--dry-run",
            "--apply",
        ],
    )

    assert result.exit_code != 0
    assert "--dry-run" in result.output
    assert "--apply" in result.output
    assert "不能同时使用" in result.output
    assert "Traceback" not in result.output


def test_sync_unknown_target_reports_clean_error_without_traceback(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "sync", "--registry", str(registry), "--to", "unknown-agent", "--dry-run"],
    )

    assert result.exit_code != 0
    assert "暂不支持目标 agent：unknown-agent" in result.output
    assert "Traceback" not in result.output


def test_sync_unknown_target_json_reports_error_envelope(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "sync",
            "--registry",
            str(registry),
            "--to",
            "unknown-agent",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-sync/v1"
    assert data["command"] == "skills sync"
    assert data["status"] == "error"
    assert data["dry_run"] is True
    assert data["data"] == {"targets": ["unknown-agent"]}
    assert data["errors"] == ["暂不支持目标 agent：unknown-agent"]
    assert data["next_steps"]
