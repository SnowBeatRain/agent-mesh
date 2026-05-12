import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.overview_service import (
    build_local_overview,
    local_overview_contract_snapshot,
)


def test_build_local_overview_reports_lightweight_local_status(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"

    overview = build_local_overview(registry)

    assert overview["schema"] == "agentmesh.local-overview/v1"
    assert overview["version"] == "0.1.0"
    assert overview["registry"] == str(registry)
    assert overview["local_first"] is True
    assert overview["default_dry_run"] is True
    assert overview["network"]["http_server"] == "not implemented"
    assert overview["network"]["dashboard_ui"] == "not implemented"
    assert overview["network"]["default_bind"] == "none"
    assert overview["local_api"]["contract_handler"] == "available"
    assert overview["local_api"]["response_schema"] == "agentmesh.local-api-response/v1"
    assert overview["local_api"]["endpoints"] == [
        "GET /health",
        "GET /doctor",
        "GET /agents",
        "GET /overview",
        "GET /skills",
        "GET /history",
        "GET /backups",
        "GET /runtime/status",
        "GET /registry/status",
        "GET /audit/summary",
        "GET /memory/status",
        "GET /model/status",
        "GET /plans/preview",
        "GET /assets/list",
        "GET /assets/detail",
        "GET /commands/schemas",
        "GET /recipes",
    ]
    assert overview["runtime"]["load_plan_schema"] == "agentmesh.runtime-load-plan/v1"
    assert overview["runtime"]["auto_load"] == "alpha groundwork"
    assert overview["runtime"]["native_load_plan_consumption"] == "not implemented"
    assert overview["safety"]["codex_system_protected"] is True
    assert overview["safety"]["claude_code_auto_install"] is False
    assert overview["agents"]


def test_overview_json_command_uses_stable_envelope(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(app, ["overview", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.overview/v1"
    assert payload["command"] == "overview"
    assert payload["status"] == "ok"
    assert payload["warnings"] == []
    assert payload["errors"] == []
    assert payload["data"]["schema"] == "agentmesh.local-overview/v1"
    assert payload["data"]["network"]["http_server"] == "not implemented"
    assert payload["data"]["runtime"]["native_load_plan_consumption"] == "not implemented"
    assert payload["next_steps"] == [
        "Run `agentmesh agents list` for runtime details.",
        "Run `agentmesh runtime load-plan --target <agent> --json` "
        "to inspect LoadPlan alpha state.",
    ]


def test_overview_human_command_is_local_lightweight_and_honest(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(app, ["overview", "--registry", str(registry)])

    assert result.exit_code == 0, result.output
    assert "AgentMesh Local Overview" in result.output
    assert "Local-first: yes" in result.output
    assert "Default dry-run: yes" in result.output
    assert "HTTP server: not implemented" in result.output
    assert "Dashboard UI: not implemented" in result.output
    assert "Runtime Auto-Load: alpha groundwork" in result.output
    assert "Native LoadPlan consumption: not implemented" in result.output
    assert "Codex .system protected: yes" in result.output
    assert "Claude Code auto-install: no" in result.output


def test_local_status_alias_matches_overview_json(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"
    runner = CliRunner()

    overview = runner.invoke(app, ["overview", "--registry", str(registry), "--json"])
    local_status = runner.invoke(app, ["local", "status", "--registry", str(registry), "--json"])

    assert overview.exit_code == 0, overview.output
    assert local_status.exit_code == 0, local_status.output
    overview_payload = json.loads(overview.output)
    local_payload = json.loads(local_status.output)
    assert local_payload["schema"] == "agentmesh.local-status/v1"
    assert local_payload["command"] == "local status"
    assert local_payload["data"] == overview_payload["data"]


def test_local_overview_contract_snapshot_pins_shape_and_safety_values(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"

    snapshot = local_overview_contract_snapshot(registry)

    assert snapshot["schema"] == "agentmesh.local-overview-contract-snapshot/v1"
    assert snapshot["overview_schema"] == "agentmesh.local-overview/v1"
    assert snapshot["top_level_keys"] == [
        "schema",
        "version",
        "registry",
        "local_first",
        "default_dry_run",
        "agents",
        "local_api",
        "network",
        "runtime",
        "safety",
    ]
    assert snapshot["agent_names"] == [
        "aider",
        "claude-code",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
        "windsurf",
    ]
    assert snapshot["agent_fields"] == [
        "capabilities",
        "installed",
        "mode",
        "name",
        "protected_paths",
        "safety_guards",
        "warnings",
        "writable",
    ]
    assert snapshot["network"] == {
        "http_server": "not implemented",
        "dashboard_ui": "not implemented",
        "default_bind": "none",
    }
    assert snapshot["local_api"] == {
        "contract_handler": "available",
        "response_schema": "agentmesh.local-api-response/v1",
        "endpoints": [
            "GET /health",
            "GET /doctor",
            "GET /agents",
            "GET /overview",
            "GET /skills",
            "GET /history",
            "GET /backups",
            "GET /runtime/status",
            "GET /registry/status",
            "GET /audit/summary",
            "GET /memory/status",
            "GET /model/status",
            "GET /plans/preview",
            "GET /assets/list",
            "GET /assets/detail",
            "GET /commands/schemas",
            "GET /recipes",
        ],
    }
    assert snapshot["runtime"] == {
        "load_plan_schema": "agentmesh.runtime-load-plan/v1",
        "auto_load": "alpha groundwork",
        "native_load_plan_consumption": "not implemented",
    }
    assert snapshot["safety"] == {
        "codex_system_protected": True,
        "claude_code_auto_install": False,
        "claude_code_export_only": True,
        "no_http_server_started": True,
        "no_dashboard_ui": True,
    }
    assert snapshot["mode_by_agent"]["claude-code"] == "export-only"
    assert snapshot["writable_by_agent"]["claude-code"] is False
    assert snapshot["protected_paths_by_agent"]["codex"] == [".system"]
    assert "no_auto_install" in snapshot["safety_guards_by_agent"]["claude-code"]
    assert "exclude_system_skills" in snapshot["safety_guards_by_agent"]["codex"]
