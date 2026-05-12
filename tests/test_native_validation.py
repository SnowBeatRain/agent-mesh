from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.validation.native import validate_native_runtime


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


def test_native_validation_skips_when_command_is_missing(tmp_path):
    result = validate_native_runtime(
        "hermes",
        tmp_path,
        which=lambda _cmd: None,
        runner=None,
    )

    assert result == {
        "target": "hermes",
        "status": "skipped",
        "command": ["hermes", "skills", "check"],
        "exit_code": None,
        "message": "native validator not found: hermes",
    }


def test_native_validation_invokes_claude_plugins_validate(tmp_path):
    calls = []

    class Completed:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    result = validate_native_runtime(
        "claude-code",
        tmp_path / "claude-plugin",
        which=lambda cmd: f"/usr/bin/{cmd}",
        runner=fake_runner,
    )

    assert calls[0][0] == ["claude", "plugins", "validate", str(tmp_path / "claude-plugin")]
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["message"] == "ok"


def test_skills_validate_native_cli_includes_native_result(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("PATH", "")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "validate",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--native",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.skills-validate/v1"
    assert payload["status"] == "ok"
    report = payload["data"]["report"]
    assert report["ok"] is True
    assert report["native_validation"] == {
        "target": "hermes",
        "status": "skipped",
        "command": ["hermes", "skills", "check"],
        "exit_code": None,
        "message": "native validator not found: hermes",
    }
