from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def make_skill(registry: Path, name: str = "demo-skill") -> None:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )


def test_root_cli_help_lists_completed_command_groups():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    for command in ["agents", "audit", "runtime", "skills"]:
        assert command in result.output


def test_core_cli_help_lists_completed_skillmesh_commands():
    runner = CliRunner()
    result = runner.invoke(app, ["skills", "--help"])

    assert result.exit_code == 0, result.output
    for command in [
        "scan",
        "import",
        "import-package",
        "list",
        "show",
        "diff",
        "validate",
        "export",
        "sync",
    ]:
        assert command in result.output


def test_doctor_json_contract_includes_schema_status_and_agents(tmp_path):
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.doctor/v1"
    assert data["command"] == "doctor"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["next_steps"]
    assert data["data"]["home"] == str(registry)
    assert sorted(agent["name"] for agent in data["data"]["agents"]) == [
        "aider",
        "claude-code",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
        "windsurf",
    ]


def test_agents_list_json_contract_is_stable():
    runner = CliRunner()

    result = runner.invoke(app, ["agents", "list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.agents-list/v1"
    assert data["command"] == "agents list"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["next_steps"]
    agents = data["data"]["agents"]
    assert sorted(agent["name"] for agent in agents) == [
        "aider",
        "claude-code",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
        "windsurf",
    ]
    for agent in agents:
        assert set(agent) == {
            "schema",
            "name",
            "installed",
            "mode",
            "writable",
            "skill_dir",
            "capabilities",
            "safety_guards",
            "protected_paths",
            "warnings",
        }
        assert agent["schema"] == "agentmesh.adapter-capabilities/v1"
        assert isinstance(agent["skill_dir"], str)
        assert isinstance(agent["capabilities"], list)
        assert isinstance(agent["safety_guards"], list)
        assert isinstance(agent["protected_paths"], list)


def test_doctor_human_output_remains_readable(tmp_path):
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--registry", str(registry)])

    assert result.exit_code == 0, result.output
    assert "AgentMesh home:" in result.output
    assert str(registry) in result.output
    for name in ["openclaw", "hermes", "codex", "claude-code", "cursor", "windsurf", "aider"]:
        assert f"- {name}:" in result.output


def test_agents_list_human_output_remains_readable():
    runner = CliRunner()

    result = runner.invoke(app, ["agents", "list"])

    assert result.exit_code == 0, result.output
    assert "Agent runtimes" in result.output
    for header in ["name", "installed", "mode", "writable", "skill_dir"]:
        assert header in result.output
    for name in ["openclaw", "hermes", "codex", "claude-code", "cursor", "windsurf", "aider"]:
        assert name in result.output


def test_skills_list_json_contract_is_stable(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "list", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-list/v1"
    assert data["command"] == "skills list"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["next_steps"]
    assert data["data"] == {"skills": ["demo-skill"], "duplicates": {}, "conflicts": []}


def test_skills_show_json_contract_is_stable(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app, ["skills", "show", "demo-skill", "--registry", str(registry), "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-show/v1"
    assert data["command"] == "skills show"
    assert data["status"] == "ok"
    assert data["data"]["skill"]["name"] == "demo-skill"
    assert data["data"]["skill"]["description"] == "Demo"
    assert "demo-skill" in data["data"]["skill"]["path"]  # Path contains skill name
    assert data["data"]["skill"]["files"]["total"] >= 2
    assert data["data"]["risk_summary"] == {"findings": 0, "secrets": 0, "scripts": 0}
    assert data["warnings"] == []
    assert data["errors"] == []


def test_skills_show_redacts_sensitive_provenance(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry, "demo-skill")
    provenance = registry / "skills" / "demo-skill" / "provenance.yaml"
    provenance.write_text(
        "source_agent: test\napi_token: secret-token-value\nnested:\n  password: secret-password\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app, ["skills", "show", "demo-skill", "--registry", str(registry), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = result.output
    assert "secret-token-value" not in payload
    assert "secret-password" not in payload
    data = json.loads(payload)
    assert data["data"]["provenance"]["api_token"] == "<redacted>"
    assert data["data"]["provenance"]["nested"]["password"] == "<redacted>"


def test_skills_show_missing_skill_returns_error(tmp_path):
    runner = CliRunner()

    result = runner.invoke(
        app, ["skills", "show", "missing", "--registry", str(tmp_path / "agentmesh"), "--json"]
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-show/v1"
    assert data["status"] == "error"
    assert data["errors"] == ["skill not found: missing"]


def test_skills_diff_json_contract_is_stable(fake_home):
    registry = fake_home / "agentmesh"
    make_skill(registry, "demo-skill")
    target = fake_home / ".hermes" / "skills" / "custom" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo\n---\n\n# Changed\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "diff",
            "demo-skill",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-diff/v1"
    assert data["command"] == "skills diff"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["next_steps"]
    assert data["data"]["skill"] == "demo-skill"
    assert data["data"]["target"] == "hermes"
    assert data["data"]["name"] == "CONTENT_CHANGED"
    assert data["data"]["changes"]


def test_audit_all_json_contract_is_stable(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(app, ["audit", "all", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.audit-all/v1"
    assert data["command"] == "audit all"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["data"]["report"]["findings"] == []
    assert data["data"]["report"]["policy"]["allowed"] is True


def test_validate_json_shape_is_stable_for_valid_registry(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "validate", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-validate/v1"
    assert data["command"] == "skills validate"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["data"]["report"] == {
        "ok": True,
        "target": "registry",
        "summary": {"skills": 1, "errors": 0, "warnings": 0},
        "findings": [],
    }


def test_export_json_shape_is_stable(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    out = tmp_path / "dist" / "claude-plugin"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "export",
            "claude-code",
            "--registry",
            str(registry),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.skills-export/v1"
    assert data["command"] == "skills export"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["data"]["target"] == "claude-code"
    assert data["data"]["out"] == str(out)
    assert data["data"]["skills"] == ["demo-skill"]
    assert data["data"]["plugin"] == str(out / "plugin.json")
