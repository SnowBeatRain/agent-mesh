"""Tests for enhanced stale detection and doctor runtime health checks."""

from __future__ import annotations

import json
import time
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.runtime_service import (
    bootstrap_status,
    detect_load_plan_staleness,
)


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


# --- detect_load_plan_staleness unit tests ---


def test_stale_when_new_skill_added_to_registry(tmp_path: Path, monkeypatch):
    """detect_load_plan_staleness should report skills_added when a new skill appears."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    # Bootstrap with only skill-a
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

    # Add a new skill after bootstrap
    make_skill(registry, "skill-b", "New skill.\n")

    load_plan_path = registry / "state" / "runtime-load-plans" / "hermes.json"
    result = detect_load_plan_staleness(registry, load_plan_path)
    assert result["stale"] is True
    assert "skill-b" in result["skills_added"]
    assert result["skills_removed"] == []


def test_stale_when_skill_removed_from_registry(tmp_path: Path, monkeypatch):
    """detect_load_plan_staleness should report skills_removed when a skill disappears."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    make_skill(registry, "skill-b")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    # Remove skill-b
    import shutil

    shutil.rmtree(registry / "registry" / "assets" / "skills" / "skill-b")

    load_plan_path = registry / "state" / "runtime-load-plans" / "hermes.json"
    result = detect_load_plan_staleness(registry, load_plan_path)
    assert result["stale"] is True
    assert "skill-b" in result["skills_removed"]
    assert result["skills_added"] == []


def test_stale_when_skill_content_modified(tmp_path: Path, monkeypatch):
    """detect_load_plan_staleness should report content_changed when skill file is newer."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a", "Original.\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    time.sleep(0.1)
    (registry / "registry" / "assets" / "skills" / "skill-a" / "SKILL.md").write_text(
        "---\nname: skill-a\ndescription: Modified\n---\n\nModified content.\n",
        encoding="utf-8",
    )

    load_plan_path = registry / "state" / "runtime-load-plans" / "hermes.json"
    result = detect_load_plan_staleness(registry, load_plan_path)
    assert result["stale"] is True
    assert "skill-a" in result["content_changed"]


def test_not_stale_when_registry_unchanged(tmp_path: Path, monkeypatch):
    """detect_load_plan_staleness should report stale=False when nothing changed."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    load_plan_path = registry / "state" / "runtime-load-plans" / "hermes.json"
    result = detect_load_plan_staleness(registry, load_plan_path)
    assert result["stale"] is False
    assert result["skills_added"] == []
    assert result["skills_removed"] == []
    assert result["content_changed"] == []


def test_stale_returns_error_when_load_plan_missing(tmp_path: Path):
    """detect_load_plan_staleness should handle missing LoadPlan gracefully."""
    load_plan_path = tmp_path / "nonexistent.json"
    result = detect_load_plan_staleness(tmp_path, load_plan_path)
    assert result["stale"] is False
    assert result["error"] is not None


# --- bootstrap_status enhanced stale detail tests ---


def test_bootstrap_status_includes_stale_details(tmp_path: Path, monkeypatch):
    """bootstrap_status should include stale_details with structural change info."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    make_skill(registry, "skill-b", "New.\n")

    result, warnings = bootstrap_status(registry, "hermes")
    assert result["plan_stale"] is True
    assert result["stale_details"]["stale"] is True
    assert "skill-b" in result["stale_details"]["skills_added"]


# --- doctor integration tests ---


def test_doctor_reports_stale_runtime(tmp_path: Path, monkeypatch):
    """am doctor should report stale runtime when LoadPlan is outdated."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    # Add a new skill to make it stale
    make_skill(registry, "skill-b", "New.\n")

    result = runner.invoke(app, ["doctor", "--registry", str(registry), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    runtime_checks = data["data"].get("runtime_checks", [])
    hermes_check = next(c for c in runtime_checks if c["target"] == "hermes")
    assert hermes_check["plan_stale"] is True
    assert hermes_check["rendered_file_exists"] is True


def test_doctor_reports_missing_rendered_file(tmp_path: Path, monkeypatch):
    """am doctor should report when rendered file is missing."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    # Delete the rendered SKILL.md
    rendered = tmp_path / ".hermes" / "skills" / "custom" / "agentmesh-loader" / "SKILL.md"
    rendered.unlink()
    assert not rendered.exists()

    result = runner.invoke(app, ["doctor", "--registry", str(registry), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    runtime_checks = data["data"].get("runtime_checks", [])
    hermes_check = next(c for c in runtime_checks if c["target"] == "hermes")
    assert hermes_check["rendered_file_exists"] is False
    assert any("missing" in w.lower() for w in hermes_check.get("warnings", []))


def test_doctor_reports_healthy_runtime(tmp_path: Path, monkeypatch):
    """am doctor should report healthy when bootstrap is fresh and files exist."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    result = runner.invoke(app, ["doctor", "--registry", str(registry), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    runtime_checks = data["data"].get("runtime_checks", [])
    hermes_check = next(c for c in runtime_checks if c["target"] == "hermes")
    assert hermes_check["plan_stale"] is False
    assert hermes_check["rendered_file_exists"] is True


def test_doctor_text_output_includes_runtime_info(tmp_path: Path, monkeypatch):
    """am doctor text output should include runtime status lines."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

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

    result = runner.invoke(app, ["doctor", "--registry", str(registry)])
    assert result.exit_code == 0, result.output
    assert "hermes" in result.output.lower()
    assert "runtime" in result.output.lower() or "loadplan" in result.output.lower()


def test_doctor_skips_targets_without_bootstrap(tmp_path: Path, monkeypatch):
    """am doctor should not report stale for targets without a bootstrap."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    # Don't bootstrap anything
    result = runner.invoke(app, ["doctor", "--registry", str(registry), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    runtime_checks = data["data"].get("runtime_checks", [])
    # All targets should be skipped or report not-installed
    for check in runtime_checks:
        assert check["installed"] is False or check.get("plan_stale") is None
