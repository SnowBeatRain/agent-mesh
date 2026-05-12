from __future__ import annotations

import json

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.prompt_service import (
    add_prompt,
    disable_prompt_target,
    enable_prompt,
    prompt_target_status,
)


def test_prompt_target_status_reports_enabled_clean(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)

    status = prompt_target_status(registry, "codex", home=fake_home)

    assert status["schema"] == "agentmesh.prompt-target-status/v1"
    assert status["target"] == "codex"
    assert status["enabled"] is True
    assert status["enabled_prompt"] == "demo-prompt"
    assert status["managed"] is True
    assert status["drift"] is False
    assert status["live_exists"] is True
    assert "AGENTS.md" in status["live_path"]  # Path contains AGENTS.md


def test_prompt_target_status_reports_drift(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    (fake_home / ".codex" / "AGENTS.md").write_text("# Edited\n", encoding="utf-8")

    status = prompt_target_status(registry, "codex", home=fake_home)

    assert status["enabled"] is True
    assert status["managed"] is True
    assert status["drift"] is True
    assert status["reason"] == "live-hash-drift"


def test_disable_prompt_target_dry_run_snapshots_drift_without_writing(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.write_text("# Edited live\n", encoding="utf-8")

    plan = disable_prompt_target(registry, "codex", apply=False, home=fake_home)

    assert plan["schema"] == "agentmesh.prompts-disable/v1"
    assert plan["target"] == "codex"
    assert plan["apply"] is False
    assert plan["will_disable_state"] is True
    assert plan["will_delete_live"] is False
    assert plan["snapshot"] is not None
    assert plan["snapshot"]["id"].startswith("imported-live-codex-")
    assert live_file.read_text(encoding="utf-8") == "# Edited live\n"
    status = prompt_target_status(registry, "codex", home=fake_home)
    assert status["enabled"] is True


def test_disable_prompt_target_apply_marks_disabled_and_keeps_live(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.write_text("# Edited live\n", encoding="utf-8")

    result = disable_prompt_target(registry, "codex", apply=True, home=fake_home)

    assert result["applied"] is True
    assert result["snapshot"] is not None
    assert live_file.exists()
    assert live_file.read_text(encoding="utf-8") == "# Edited live\n"
    status = prompt_target_status(registry, "codex", home=fake_home)
    assert status["enabled"] is False
    assert status["enabled_prompt"] is None
    assert status["managed"] is True
    assert status["live_exists"] is True


def test_prompts_status_cli_json(fake_home, monkeypatch):
    monkeypatch.setattr("agentmesh.config.loader.user_home", lambda: fake_home)
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    runner = CliRunner()

    result = runner.invoke(
        app, ["prompts", "status", "--target", "codex", "--registry", str(registry), "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.prompts-status/v1"
    assert data["command"] == "prompts status"
    assert data["status"] == "ok"
    assert data["data"]["status"]["enabled_prompt"] == "demo-prompt"


def test_prompts_disable_cli_json_dry_run_and_apply(fake_home, monkeypatch):
    monkeypatch.setattr("agentmesh.config.loader.user_home", lambda: fake_home)
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    runner = CliRunner()

    dry_run = runner.invoke(
        app,
        [
            "prompts",
            "disable",
            "--target",
            "codex",
            "--registry",
            str(registry),
            "--dry-run",
            "--json",
        ],
    )

    assert dry_run.exit_code == 0, dry_run.output
    dry_data = json.loads(dry_run.output)
    assert dry_data["schema"] == "agentmesh.prompts-disable/v1"
    assert dry_data["status"] == "planned"
    assert dry_data["dry_run"] is True

    applied = runner.invoke(
        app,
        [
            "prompts",
            "disable",
            "--target",
            "codex",
            "--registry",
            str(registry),
            "--apply",
            "--json",
        ],
    )

    assert applied.exit_code == 0, applied.output
    applied_data = json.loads(applied.output)
    assert applied_data["status"] == "applied"
    assert applied_data["dry_run"] is False
    assert prompt_target_status(registry, "codex", home=fake_home)["enabled"] is False


def test_disable_prompt_target_dry_run_does_not_create_snapshot_prompt(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    (fake_home / ".codex" / "AGENTS.md").write_text("# Edited live\n", encoding="utf-8")

    plan = disable_prompt_target(registry, "codex", apply=False, home=fake_home)

    assert plan["snapshot"]["would_create"] is True
    imported = list((registry / "prompts").glob("imported-live-codex-*"))
    assert imported == []


def test_disable_prompt_target_apply_persists_snapshot_prompt_id(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    (fake_home / ".codex" / "AGENTS.md").write_text("# Edited live\n", encoding="utf-8")

    result = disable_prompt_target(registry, "codex", apply=True, home=fake_home)
    status = prompt_target_status(registry, "codex", home=fake_home)

    snapshot_id = result["snapshot"]["id"]
    assert status["last_snapshot_prompt"] == snapshot_id
    snapshot_content = (registry / "prompts" / snapshot_id / "PROMPT.md").read_text(
        encoding="utf-8"
    )
    assert snapshot_content == "# Edited live\n"


def test_prompt_target_status_reports_missing_state_hash(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    enable_prompt(registry, "demo-prompt", "codex", apply=True, home=fake_home)
    state_path = registry / "state" / "prompts.yaml"
    state_path.write_text(
        "schema: agentmesh.prompts-state/v1\ntargets:\n  codex:\n    enabled_prompt: demo-prompt\n",
        encoding="utf-8",
    )

    status = prompt_target_status(registry, "codex", home=fake_home)

    assert status["drift"] is False
    assert status["drift_unknown"] is True
    assert status["reason"] == "state-hash-missing"


def test_prompts_status_unknown_target_json_errors(fake_home):
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "prompts",
            "status",
            "--target",
            "unknown",
            "--registry",
            str(fake_home / "agentmesh"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert "暂不支持 prompt target" in data["errors"][0]
    assert "Traceback" not in result.output


def test_prompts_disable_unknown_target_json_errors(fake_home):
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "prompts",
            "disable",
            "--target",
            "unknown",
            "--registry",
            str(fake_home / "agentmesh"),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert "暂不支持 prompt target" in data["errors"][0]
    assert "Traceback" not in result.output
