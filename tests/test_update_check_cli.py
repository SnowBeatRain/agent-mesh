from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def make_registry_skill(registry: Path, name: str) -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (skill / "agentmesh.asset.yaml").write_text(
        "\n".join(
            [
                "schema: agentmesh.asset/v1",
                "kind: skill",
                f"name: {name}",
                f"description: {name}",
                "source:",
                "  kind: agentmesh-package",
                "  package_path: demo-package.zip",
                "  package_sha256: sha256:abc123",
                "  original_hash: def456",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return skill


def test_skills_update_check_json_outputs_contract(tmp_path):
    registry = tmp_path / "agentmesh-home"
    make_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "update-check", "--registry", str(registry), "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.update-check/v1"
    assert data["command"] == "skills update-check"
    assert data["status"] == "ok"
    assert data["data"]["network"] == "disabled"
    assert data["data"]["summary"]["unknown"] == 1
    assert data["data"]["skills"][0]["remote_checked"] is False


def test_skills_update_check_human_output_uses_m7_summary(tmp_path):
    registry = tmp_path / "agentmesh-home"
    make_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "update-check", "--registry", str(registry)])

    assert result.exit_code == 0, result.output
    assert "0 candidate, 1 unknown, 0 skipped" in result.output
    assert "demo-skill: unknown (network-disabled)" in result.output
