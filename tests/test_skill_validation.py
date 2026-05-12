from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.validation.skills import validate_registry_skills


def make_skill(registry: Path, name: str, skill_md: str, manifest: str | None = None) -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(skill_md, encoding="utf-8")
    if manifest is not None:
        (skill / "agentmesh.asset.yaml").write_text(manifest, encoding="utf-8")
    return skill


def test_validate_registry_skills_reports_errors_and_warnings(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(
        registry,
        "good-skill",
        "---\nname: good-skill\ndescription: Good\n---\n\n# Good\n",
        "schema: agentmesh.asset/v1\nkind: skill\nname: good-skill\ndescription: Good\n",
    )
    make_skill(registry, "missing-manifest", "---\nname: missing-manifest\n---\n\n# Missing\n")
    make_skill(
        registry,
        "name-mismatch",
        "---\nname: different\ndescription: Different\n---\n\n# Different\n",
        "schema: agentmesh.asset/v1\nkind: skill\nname: name-mismatch\ndescription: Mismatch\n",
    )
    make_skill(
        registry,
        "unsafe-skill",
        "---\nname: unsafe-skill\n---\n\ntoken = abc123\n",
        "schema: agentmesh.asset/v1\nkind: skill\nname: unsafe-skill\n",
    )

    report = validate_registry_skills(registry)

    assert report["ok"] is False
    assert report["summary"]["skills"] == 4
    assert report["summary"]["errors"] >= 2
    assert any(item["code"] == "missing-manifest" for item in report["findings"])
    assert any(item["code"] == "frontmatter-name-mismatch" for item in report["findings"])
    assert any(item["code"] == "audit-block" for item in report["findings"])
    assert "abc123" not in json.dumps(report, ensure_ascii=False)


def test_skills_validate_cli_returns_nonzero_on_errors(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry, "bad-skill", "# no frontmatter\n")
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "validate", "--registry", str(registry), "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.skills-validate/v1"
    assert payload["status"] == "error"
    report = payload["data"]["report"]
    assert report["ok"] is False
    assert any(item["code"] == "missing-frontmatter-name" for item in report["findings"])
