from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.registry_service import reindex_registry_skills


def make_skill(registry: Path, name: str, description: str = "Demo") -> Path:
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


def test_reindex_registry_skills_writes_deterministic_index(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry, "zeta-skill", "Zeta")
    make_skill(registry, "alpha-skill", "Alpha")

    index = reindex_registry_skills(registry)

    assert index["schema"] == "agentmesh.registry-skills-index/v1"
    assert index["summary"] == {"skills": 2}
    assert [item["name"] for item in index["skills"]] == ["alpha-skill", "zeta-skill"]
    assert index["skills"][0]["description"] == "Alpha"
    assert "SKILL.md" in index["skills"][0]["files"]
    index_path = registry / "registry" / "index" / "skills.json"
    assert json.loads(index_path.read_text(encoding="utf-8")) == index


def test_skills_reindex_json_envelope(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "reindex", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.skills-reindex/v1"
    assert payload["command"] == "skills reindex"
    assert payload["status"] == "ok"
    assert payload["warnings"] == []
    assert payload["errors"] == []
    assert payload["data"]["index"]["schema"] == "agentmesh.registry-skills-index/v1"
    assert "skills.json" in payload["data"]["index_path"]  # Path contains skills.json
    assert payload["summary"] == {"skills": 1}


def test_skills_help_lists_reindex_command():
    result = CliRunner().invoke(app, ["skills", "--help"])

    assert result.exit_code == 0, result.output
    assert "reindex" in result.output
