from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.skill_state_service import enabled_sync_pairs, set_skill_targets


def make_registry_skill(registry: Path, name: str, body: str = "# Demo\n") -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}", encoding="utf-8"
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    return skill


def test_skill_state_enable_disable_and_pairs(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill")

    status = set_skill_targets(registry, "demo-skill", "hermes,codex", enabled=True)

    assert status["skill"] == "demo-skill"
    assert status["targets"]["hermes"]["enabled"] is True
    assert status["targets"]["codex"]["mode"] == "copy"
    assert enabled_sync_pairs(registry) == [
        {"skill": "demo-skill", "target": "codex"},
        {"skill": "demo-skill", "target": "hermes"},
    ]

    status = set_skill_targets(registry, "demo-skill", "codex", enabled=False)

    assert status["targets"]["codex"]["enabled"] is False
    assert enabled_sync_pairs(registry) == [{"skill": "demo-skill", "target": "hermes"}]


def test_skills_enable_status_cli_and_sync_enabled(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill")
    make_registry_skill(registry, "other-skill")
    runner = CliRunner()

    enabled = runner.invoke(
        app,
        [
            "skills",
            "enable",
            "demo-skill",
            "--target",
            "hermes,codex",
            "--registry",
            str(registry),
            "--json",
        ],
    )
    assert enabled.exit_code == 0, enabled.output
    enabled_data = json.loads(enabled.output)
    assert enabled_data["targets"]["hermes"]["enabled"] is True

    status = runner.invoke(
        app, ["skills", "status", "demo-skill", "--registry", str(registry), "--json"]
    )
    assert status.exit_code == 0, status.output
    status_data = json.loads(status.output)
    assert status_data["schema"] == "agentmesh.skills-status/v1"
    assert status_data["command"] == "skills status"
    assert status_data["status"] == "ok"
    assert status_data["warnings"] == []
    assert status_data["errors"] == []
    assert status_data["data"]["state"]["targets"]["codex"]["enabled"] is True

    plan = runner.invoke(
        app, ["skills", "sync", "--registry", str(registry), "--enabled", "--dry-run", "--json"]
    )
    assert plan.exit_code == 0, plan.output
    data = json.loads(plan.output)
    actions = data["data"]["plan"]["actions"]
    assert {item["skill"] for item in actions} == {"demo-skill"}
    assert {item["to"] for item in actions} == {"hermes", "codex"}


def test_skills_enable_rejects_missing_skill(tmp_path):
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "enable",
            "missing-skill",
            "--target",
            "hermes",
            "--registry",
            str(registry),
        ],
    )

    assert result.exit_code != 0
    assert "registry 中不存在 skill" in result.output
    assert "Traceback" not in result.output


def test_skills_sync_requires_to_unless_enabled(tmp_path):
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "sync", "--registry", str(registry), "--dry-run"])

    assert result.exit_code != 0
    assert "必须指定 --to" in result.output
    assert "Traceback" not in result.output
