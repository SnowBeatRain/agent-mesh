from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.exporters.claude_code import export_claude_code_package


def make_registry_skill(registry: Path, name: str, description: str = "Demo skill") -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: {description}\n",
        encoding="utf-8",
    )
    return skill


def test_export_claude_code_package_builds_plugin_layout(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill")
    out = tmp_path / "dist" / "claude-plugin"

    result = export_claude_code_package(registry, out)

    assert result["target"] == "claude-code"
    assert result["skills"] == ["demo-skill"]
    assert (out / "plugin.json").exists()
    assert (out / "skills" / "demo-skill" / "SKILL.md").exists()
    assert (out / "README.md").exists()
    plugin = json.loads((out / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "agentmesh-skills"
    assert plugin["version"] == "0.1.0"
    assert plugin["skills"] == [{"name": "demo-skill", "path": "skills/demo-skill/SKILL.md"}]


def test_skills_export_claude_code_cli(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill")
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
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.skills-export/v1"
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["target"] == "claude-code"
    assert data["out"] == str(out)
    assert data["skills"] == ["demo-skill"]
    assert (out / "plugin.json").exists()
