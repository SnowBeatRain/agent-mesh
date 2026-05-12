from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def make_registry_skill(registry: Path, name: str, body: str = "# Registry") -> None:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_sync_apply_reports_policy_block_without_traceback(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill", "api_key = 'super-secret-value'")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["skills", "sync", "--registry", str(registry), "--to", "openclaw", "--apply", "--yes"],
    )

    assert result.exit_code != 0
    assert "同步被阻止" in result.output
    assert "super-secret-value" not in result.output
    assert "Traceback" not in result.output
