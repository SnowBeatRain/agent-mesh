import json
from pathlib import Path

import pytest

from agentmesh.local_api.service import handle_readonly_request, local_api_contract_snapshot


def test_local_api_health_returns_standard_envelope(tmp_path: Path):
    response = handle_readonly_request("GET", "/health", registry=tmp_path)

    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api health"
    assert response["status"] == "ok"
    assert response["warnings"] == []
    assert response["errors"] == []
    assert response["next_steps"] == []
    assert response["data"]["service"] == "agentmesh-local-api"
    assert response["data"]["mode"] == "read-only"
    assert response["data"]["registry"].startswith("~/")  # Path should be redacted


def test_local_api_agents_returns_capabilities_contract(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"

    response = handle_readonly_request("GET", "/agents", registry=registry)

    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api agents list"
    assert response["status"] == "ok"
    agents = response["data"]["agents"]
    assert {agent["name"] for agent in agents} == {
        "hermes",
        "openclaw",
        "codex",
        "claude-code",
        "cursor",
        "windsurf",
        "aider",
    }
    codex = next(agent for agent in agents if agent["name"] == "codex")
    assert ".system" in codex["protected_paths"]
    assert "exclude_system_skills" in codex["safety_guards"]


def test_local_api_doctor_reuses_readonly_runtime_inventory(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"

    response = handle_readonly_request("GET", "/doctor", registry=registry)

    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api doctor"
    assert response["status"] == "ok"
    assert response["data"]["registry"].startswith("~/")  # Path should be redacted
    assert {agent["name"] for agent in response["data"]["agents"]} == {
        "hermes",
        "openclaw",
        "codex",
        "claude-code",
        "cursor",
        "windsurf",
        "aider",
    }


def test_local_api_overview_skills_history_backups_runtime_status_are_readonly(
    tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"
    skill = registry / "skills" / "demo-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (skill / "agentmesh.asset.yaml").write_text(
        "schema: agentmesh.asset/v1\nkind: skill\nname: demo-skill\ndescription: Demo\n",
        encoding="utf-8",
    )

    for path, command in [
        ("/overview", "local-api overview"),
        ("/skills", "local-api skills list"),
        ("/history", "local-api history list"),
        ("/backups", "local-api backup list"),
        ("/runtime/status", "local-api runtime status"),
        ("/registry/status", "local-api registry status"),
        ("/audit/summary", "local-api audit summary"),
        ("/memory/status", "local-api memory status"),
        ("/model/status", "local-api model status"),
    ]:
        response = handle_readonly_request("GET", path, registry=registry)
        assert response["schema"] == "agentmesh.local-api-response/v1"
        assert response["command"] == command
        assert response["status"] in {"ok", "not-installed", "installed"}
        assert response["errors"] == []

    skills = handle_readonly_request("GET", "/skills", registry=registry)
    assert skills["data"]["skills"] == ["demo-skill"]

    runtime_status = handle_readonly_request("GET", "/runtime/status", registry=registry)
    assert runtime_status["data"]["target"] == "hermes"


def test_local_api_rejects_non_readonly_methods(tmp_path: Path):
    response = handle_readonly_request("POST", "/agents", registry=tmp_path)

    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["status"] == "blocked"
    assert response["data"] == {"method": "POST", "path": "/agents"}
    assert response["errors"] == ["local API alpha is read-only; POST is not allowed"]
    assert response["next_steps"] == ["Use GET endpoints or the CLI for explicit write operations."]


def test_local_api_unknown_route_returns_error_envelope(tmp_path: Path):
    response = handle_readonly_request("GET", "/missing", registry=tmp_path)

    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["status"] == "error"
    assert response["data"] == {"method": "GET", "path": "/missing"}
    assert response["errors"] == ["unknown local API route: GET /missing"]


def test_local_api_contract_snapshot_pins_public_envelope_shape(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"

    snapshot = local_api_contract_snapshot(registry=registry)

    assert snapshot["schema"] == "agentmesh.local-api-contract-snapshot/v1"
    assert snapshot["summary"] == {"endpoints": 17, "read_only": True}
    assert [item["path"] for item in snapshot["endpoints"]] == [
        "/health",
        "/doctor",
        "/agents",
        "/overview",
        "/skills",
        "/history",
        "/backups",
        "/runtime/status",
        "/registry/status",
        "/audit/summary",
        "/memory/status",
        "/model/status",
        "/plans/preview",
        "/assets/list",
        "/assets/detail",
        "/commands/schemas",
        "/recipes",
    ]
    for item in snapshot["endpoints"]:
        assert item["method"] == "GET"
        assert item["response_schema"] == "agentmesh.local-api-response/v1"
        assert item["status"] in {"ok", "not-installed", "error", "installed"}
        assert item["envelope_keys"] == [
            "schema",
            "command",
            "status",
            "data",
            "warnings",
            "errors",
            "next_steps",
        ]
        assert item["data_keys"]


def test_local_api_contract_snapshot_pins_safety_fields(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    snapshot = local_api_contract_snapshot(registry=tmp_path / "agentmesh")
    agents = next(item for item in snapshot["endpoints"] if item["path"] == "/agents")

    assert agents["agent_names"] == [
        "aider",
        "claude-code",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
        "windsurf",
    ]
    assert agents["safety_fields"] == [
        "capabilities",
        "mode",
        "protected_paths",
        "safety_guards",
        "writable",
    ]
    assert agents["protected_paths_by_agent"]["codex"] == [".system"]
    assert agents["mode_by_agent"]["claude-code"] == "export-only"
    assert agents["writable_by_agent"]["claude-code"] is False
    assert "exclude_system_skills" in agents["safety_guards_by_agent"]["codex"]
    assert "dry_run_default" in agents["safety_guards_by_agent"]["codex"]
    assert "no_auto_install" in agents["safety_guards_by_agent"]["claude-code"]
    assert "apply_sync" in agents["capabilities_by_agent"]["codex"]
    assert "apply_sync" not in agents["capabilities_by_agent"]["claude-code"]


def test_local_api_response_is_json_serializable(tmp_path: Path):
    response = handle_readonly_request("GET", "/agents", registry=tmp_path)

    json.dumps(response, ensure_ascii=False)


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def test_local_api_rejects_all_non_get_methods(tmp_path: Path, method: str):
    response = handle_readonly_request(method, "/agents", registry=tmp_path)

    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["status"] == "blocked"
    assert response["data"] == {"method": method, "path": "/agents"}
    assert response["errors"] == [f"local API alpha is read-only; {method} is not allowed"]


def test_local_api_health_redacts_home_path(tmp_path: Path, monkeypatch):
    """M4: handler output should redact absolute home paths."""
    home = tmp_path / "real-home"
    monkeypatch.setenv("HOME", str(home))
    registry = home / ".agentmesh"
    response = handle_readonly_request("GET", "/health", registry=registry)

    raw_registry = response["data"]["registry"]
    assert str(home) not in raw_registry, "absolute home path leaked into /health response"
    assert raw_registry.startswith("~/")


def test_local_api_doctor_redacts_home_path(tmp_path: Path, monkeypatch):
    """M4: handler output should redact absolute home paths in /doctor."""
    home = tmp_path / "real-home"
    monkeypatch.setenv("HOME", str(home))
    registry = home / ".agentmesh"
    response = handle_readonly_request("GET", "/doctor", registry=registry)

    raw = json.dumps(response, ensure_ascii=False)
    assert str(home) not in raw, "absolute home path leaked into /doctor response"


def test_local_api_registry_status_returns_counts(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"
    skill = registry / "skills" / "demo-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (skill / "agentmesh.asset.yaml").write_text(
        "schema: agentmesh.asset/v1\nkind: skill\nname: demo-skill\ndescription: Demo\n",
        encoding="utf-8",
    )

    response = handle_readonly_request("GET", "/registry/status", registry=registry)
    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api registry status"
    assert response["status"] == "ok"
    data = response["data"]
    assert data["skills_count"] == 1
    assert data["skills"] == ["demo-skill"]
    assert data["agents_count"] >= 0  # May detect real agents in development environment
    assert data["total_agents"] >= 1


def test_local_api_audit_summary_returns_findings_counts(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"
    skill = registry / "skills" / "risky-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "# Risky\napi_key = 'SECRET123'\ncurl | bash\n~/.hermes/config.yaml\n",
        encoding="utf-8",
    )

    response = handle_readonly_request("GET", "/audit/summary", registry=registry)
    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api audit summary"
    assert response["status"] == "ok"
    data = response["data"]
    assert data["secrets"] >= 1
    assert data["dangerous_scripts"] >= 1
    assert data["platform_refs"] >= 1
    assert data["total_findings"] >= 3
    assert data["allowed"] is False


def test_local_api_memory_status_returns_empty(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"

    response = handle_readonly_request("GET", "/memory/status", registry=registry)
    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api memory status"
    assert response["status"] == "ok"
    assert response["data"]["total_memories"] == 0


def test_local_api_model_status_returns_configs(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    registry = tmp_path / "agentmesh"

    response = handle_readonly_request("GET", "/model/status", registry=registry)
    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api model status"
    assert response["status"] == "ok"
    data = response["data"]
    assert "total_configs" in data
    assert "configs" in data
    assert "diffs" in data


def test_local_api_new_endpoints_redact_paths(tmp_path: Path, monkeypatch):
    """新端点也应正确脱敏绝对路径。"""
    home = tmp_path / "real-home"
    monkeypatch.setenv("HOME", str(home))
    registry = home / ".agentmesh"

    for path in ["/registry/status", "/audit/summary", "/memory/status", "/model/status"]:
        response = handle_readonly_request("GET", path, registry=registry)
        raw = json.dumps(response, ensure_ascii=False)
        assert str(home) not in raw, f"absolute home path leaked into {path} response"
