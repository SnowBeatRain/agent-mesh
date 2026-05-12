from __future__ import annotations

import json

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.prompt_service import add_prompt, enable_prompt, list_prompts


def test_prompt_add_list_and_enable_dry_run(fake_home):
    registry = fake_home / "agentmesh"
    prompt_file = fake_home / "review.md"
    prompt_file.write_text("# Review prompt\n", encoding="utf-8")
    runner = CliRunner()

    added = runner.invoke(
        app,
        [
            "prompts",
            "add",
            "review-prompt",
            "--name",
            "Review Prompt",
            "--from",
            str(prompt_file),
            "--registry",
            str(registry),
            "--json",
        ],
    )
    assert added.exit_code == 0, added.output
    assert json.loads(added.output)["id"] == "review-prompt"

    listed = runner.invoke(app, ["prompts", "list", "--registry", str(registry), "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)["data"]["prompts"][0]["id"] == "review-prompt"

    planned = runner.invoke(
        app,
        [
            "prompts",
            "enable",
            "review-prompt",
            "--target",
            "codex",
            "--registry",
            str(registry),
            "--dry-run",
            "--json",
        ],
    )
    assert planned.exit_code == 0, planned.output
    data = json.loads(planned.output)
    assert data["status"] == "planned"
    assert data["dry_run"] is True
    assert data["data"]["plan"]["live_path"].endswith(".codex\\AGENTS.md") or data["data"]["plan"][
        "live_path"
    ].endswith(".codex/AGENTS.md")
    assert not (fake_home / ".codex" / "AGENTS.md").exists()


def test_prompt_enable_apply_snapshots_existing_live_file(fake_home):
    registry = fake_home / "agentmesh"
    add_prompt(registry, "new-prompt", "New Prompt", "# New prompt\n")
    live_file = fake_home / ".codex" / "AGENTS.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# Hand edited live prompt\n", encoding="utf-8")

    result = enable_prompt(registry, "new-prompt", "codex", apply=True, home=fake_home)

    assert result["snapshot"] is not None
    assert result["snapshot"]["id"].startswith("imported-live-codex-")
    assert live_file.read_text(encoding="utf-8") == "# New prompt\n"
    prompts = {item["id"] for item in list_prompts(registry)}
    assert "new-prompt" in prompts
    assert result["snapshot"]["id"] in prompts


def test_prompt_import_live_cli(fake_home):
    registry = fake_home / "agentmesh"
    live_file = fake_home / ".claude" / "CLAUDE.md"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("# Claude live prompt\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "prompts",
            "import-live",
            "--target",
            "claude-code",
            "--registry",
            str(registry),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["id"].startswith("imported-live-claude-code-")


def test_prompt_enable_rejects_unknown_target(tmp_path):
    registry = tmp_path / "agentmesh"
    add_prompt(registry, "demo-prompt", "Demo", "# Demo\n")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "prompts",
            "enable",
            "demo-prompt",
            "--target",
            "unknown-agent",
            "--registry",
            str(registry),
            "--dry-run",
        ],
    )

    assert result.exit_code != 0
    assert "暂不支持 prompt target" in result.output
    assert "Traceback" not in result.output
