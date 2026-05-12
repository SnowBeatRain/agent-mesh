"""Tests for Runtime Auto-Load Hook mechanism.

Covers: hook generation, install/uninstall, bootstrap integration,
disable integration, check-stale service, and CLI command.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.runtime_service import (
    apply_bootstrap,
    build_auto_load_hook_content,
    check_stale,
    disable_bootstrap,
    install_auto_load_hook,
    uninstall_auto_load_hook,
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


# --- hook content generation ---


def test_build_auto_load_hook_content_includes_target_and_paths(tmp_path):
    """Hook script content should reference target, agentmesh_home, and load_plan."""
    agentmesh_home = tmp_path / "agentmesh"
    content = build_auto_load_hook_content("hermes", agentmesh_home)

    assert "#!/usr/bin/env bash" in content
    assert "hermes" in content
    assert str(agentmesh_home) in content
    assert "runtime check-stale" in content
    assert "runtime update" in content
    assert "agentmesh-auto-load.sh" not in content  # no self-reference needed


def test_build_auto_load_hook_content_is_valid_bash(tmp_path):
    """Generated hook script should pass bash -n syntax check."""
    agentmesh_home = tmp_path / "agentmesh"
    content = build_auto_load_hook_content("openclaw", agentmesh_home)
    hook_file = tmp_path / "test-hook.sh"
    hook_file.write_text(content, encoding="utf-8")

    result = subprocess.run(
        ["bash", "-n", str(hook_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Bash syntax error: {result.stderr}"


# --- install / uninstall ---


def test_install_auto_load_hook_creates_executable_script(tmp_path, monkeypatch):
    """install_auto_load_hook should create an executable hook script."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    hook_path = install_auto_load_hook(agentmesh_home, "hermes")

    assert hook_path.exists()
    assert hook_path.name == "agentmesh-auto-load.sh"
    assert hook_path.stat().st_mode & stat.S_IXUSR
    content = hook_path.read_text(encoding="utf-8")
    assert "hermes" in content
    assert str(agentmesh_home) in content


def test_install_auto_load_hook_idempotent(tmp_path, monkeypatch):
    """Installing hook twice should overwrite without error."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    hook_path = install_auto_load_hook(agentmesh_home, "hermes")
    assert hook_path.exists()

    hook_path2 = install_auto_load_hook(agentmesh_home, "hermes")
    assert hook_path == hook_path2
    content_v2 = hook_path2.read_text(encoding="utf-8")
    # Content differs only by timestamp; both should be valid
    assert "#!/usr/bin/env bash" in content_v2
    assert "hermes" in content_v2
    assert str(agentmesh_home) in content_v2


def test_uninstall_auto_load_hook_removes_file(tmp_path, monkeypatch):
    """uninstall_auto_load_hook should remove the hook script."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    hook_path = install_auto_load_hook(agentmesh_home, "hermes")
    assert hook_path.exists()

    result = uninstall_auto_load_hook("hermes", home=tmp_path)
    assert result is True
    assert not hook_path.exists()


def test_uninstall_auto_load_hook_returns_false_when_missing(tmp_path, monkeypatch):
    """uninstall should return False when no hook exists."""
    monkeypatch.setenv("HOME", str(tmp_path))
    result = uninstall_auto_load_hook("hermes", home=tmp_path)
    assert result is False


# --- bootstrap integration ---


def test_bootstrap_apply_installs_hook(tmp_path, monkeypatch):
    """apply_bootstrap should install the auto-load hook."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = apply_bootstrap(agentmesh_home, "hermes")
    assert result["applied"] is True

    hook_path = tmp_path / ".hermes" / "agentmesh-auto-load.sh"
    assert hook_path.exists()
    assert hook_path.stat().st_mode & stat.S_IXUSR
    assert "hermes" in hook_path.read_text(encoding="utf-8")


def test_bootstrap_apply_returns_hook_path_in_result(tmp_path, monkeypatch):
    """apply_bootstrap result should include hook_path."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = apply_bootstrap(agentmesh_home, "hermes")
    assert "hook_path" in result
    assert Path(result["hook_path"]).exists()


# --- disable integration ---


def test_disable_bootstrap_uninstalls_hook(tmp_path, monkeypatch):
    """disable_bootstrap with apply=True should remove the auto-load hook."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    apply_bootstrap(agentmesh_home, "hermes")
    hook_path = tmp_path / ".hermes" / "agentmesh-auto-load.sh"
    assert hook_path.exists()

    disable_bootstrap(agentmesh_home, "hermes", apply=True)
    assert not hook_path.exists()


# --- check-stale service ---


def test_check_stale_returns_fresh_when_unchanged(tmp_path, monkeypatch):
    """check_stale should report stale=False when LoadPlan matches registry."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    apply_bootstrap(agentmesh_home, "hermes")
    result = check_stale(agentmesh_home, "hermes")

    assert result["target"] == "hermes"
    assert result["stale"] is False
    assert result["skills_added"] == []
    assert result["skills_removed"] == []
    assert result["content_changed"] == []


def test_check_stale_returns_stale_when_skill_added(tmp_path, monkeypatch):
    """check_stale should report stale=True when a new skill appears."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))

    apply_bootstrap(agentmesh_home, "hermes")
    make_skill(agentmesh_home, "skill-b", "New.\n")

    result = check_stale(agentmesh_home, "hermes")
    assert result["stale"] is True
    assert "skill-b" in result["skills_added"]


def test_check_stale_handles_missing_load_plan(tmp_path):
    """check_stale should handle missing LoadPlan gracefully."""
    agentmesh_home = tmp_path / "agentmesh"
    agentmesh_home.mkdir(parents=True, exist_ok=True)

    result = check_stale(agentmesh_home, "hermes")
    assert result["stale"] is False
    assert result["error"] is not None


# --- CLI check-stale command ---


def test_cli_check_stale_command(tmp_path, monkeypatch):
    """runtime check-stale CLI command should return JSON with staleness info."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    # Bootstrap first
    runner.invoke(
        app,
        [
            "runtime", "bootstrap",
            "--registry", str(agentmesh_home),
            "--target", "hermes",
            "--apply", "--json",
        ],
    )

    result = runner.invoke(
        app,
        [
            "runtime", "check-stale",
            "--registry", str(agentmesh_home),
            "--target", "hermes",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.runtime-check-stale/v1"
    assert data["data"]["target"] == "hermes"
    assert data["data"]["stale"] is False


def test_cli_check_stale_detects_staleness(tmp_path, monkeypatch):
    """runtime check-stale should detect when registry changed."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home, "skill-a")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    runner.invoke(
        app,
        [
            "runtime", "bootstrap",
            "--registry", str(agentmesh_home),
            "--target", "hermes",
            "--apply", "--json",
        ],
    )

    make_skill(agentmesh_home, "skill-b", "New.\n")

    result = runner.invoke(
        app,
        [
            "runtime", "check-stale",
            "--registry", str(agentmesh_home),
            "--target", "hermes",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["stale"] is True
    assert "skill-b" in data["data"]["skills_added"]


# --- CLI bootstrap shows hook info ---


def test_cli_bootstrap_apply_reports_hook_installed(tmp_path, monkeypatch):
    """bootstrap --apply --json should include hook_path in result."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "runtime", "bootstrap",
            "--registry", str(agentmesh_home),
            "--target", "hermes",
            "--apply", "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "hook_path" in data["data"]
    assert Path(data["data"]["hook_path"]).exists()


# --- hook installed for all supported targets ---


def test_hook_installed_for_all_targets(tmp_path, monkeypatch):
    """Auto-load hook should be installed for every supported target."""
    agentmesh_home = tmp_path / "agentmesh"
    make_skill(agentmesh_home)
    monkeypatch.setenv("HOME", str(tmp_path))

    targets = {
        "hermes": tmp_path / ".hermes" / "agentmesh-auto-load.sh",
        "openclaw": tmp_path / ".openclaw" / "agentmesh-auto-load.sh",
        "cursor": tmp_path / ".cursor" / "agentmesh-auto-load.sh",
        "windsurf": tmp_path / ".windsurf" / "agentmesh-auto-load.sh",
    }

    for target, expected_hook in targets.items():
        apply_bootstrap(agentmesh_home, target)
        assert expected_hook.exists(), f"Hook missing for {target}: {expected_hook}"
        content = expected_hook.read_text(encoding="utf-8")
        assert target in content
