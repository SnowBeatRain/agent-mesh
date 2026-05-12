"""Additional runtime tests: stale detection and update command."""

from __future__ import annotations

import json
import time
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def make_skill(registry: Path, name: str = "demo-skill", body: str = "# Demo\n") -> None:
    skill = registry / "registry" / "assets" / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\n",
        encoding="utf-8",
    )


def test_runtime_status_shows_stale_when_registry_newer_than_plan(tmp_path: Path, monkeypatch):
    """runtime status should warn when registry was modified after LoadPlan."""
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    # Bootstrap to create LoadPlan
    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--apply",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output

    # Wait, then modify registry
    time.sleep(0.1)
    skill_file = registry / "registry" / "assets" / "skills" / "demo-skill" / "SKILL.md"
    skill_file.write_text(
        "---\nname: demo-skill\ndescription: Updated\n---\n\nUpdated.\n",
        encoding="utf-8",
    )

    status = runner.invoke(
        app,
        ["runtime", "status", "--registry", str(registry), "--target", "hermes", "--json"],
    )
    assert status.exit_code == 0, status.output
    data = json.loads(status.output)
    assert any("stale" in w.lower() or "outdated" in w.lower() for w in data.get("warnings", []))


def test_runtime_update_renders_fresh_content(tmp_path: Path, monkeypatch):
    """runtime update should regenerate LoadPlan and re-render skills."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a", "Original content.\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    # Initial bootstrap
    runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--apply",
            "--json",
        ],
    )

    # Modify skill and add new one
    skill = registry / "registry" / "assets" / "skills" / "skill-a" / "SKILL.md"
    skill.write_text(
        "---\nname: skill-a\ndescription: Updated\n---\n\nUpdated content.\n",
        encoding="utf-8",
    )
    make_skill(registry, "skill-b", "New skill.\n")

    # Update
    result = runner.invoke(
        app,
        [
            "runtime",
            "update",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--apply",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "updated"
    assert data["data"]["rendered_skills"] == 2

    # Verify rendered content
    loader = tmp_path / ".hermes" / "skills" / "custom" / "agentmesh-loader"
    skill_md = (loader / "SKILL.md").read_text(encoding="utf-8")
    assert "Updated content" in skill_md
    assert "## skill-b" in skill_md
