"""Tests for the Local API HTTP server wrapper."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from agentmesh.local_api.server import create_server


@pytest.fixture
def api_server(tmp_path: Path):
    """Start the API server on a random available port, yield base URL, then shut down."""
    import socket

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = create_server(host="127.0.0.1", port=port, registry=tmp_path)

    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    import time

    time.sleep(0.2)  # Let server start

    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def _get(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_server_health_returns_ok(api_server: str):
    data = _get(f"{api_server}/health")
    assert data["schema"] == "agentmesh.local-api-response/v1"
    assert data["status"] == "ok"
    assert data["data"]["service"] == "agentmesh-local-api"


def test_server_agents_returns_capabilities(api_server: str):
    data = _get(f"{api_server}/agents")
    assert data["status"] == "ok"
    names = {a["name"] for a in data["data"]["agents"]}
    assert "hermes" in names
    assert "codex" in names


def test_server_unknown_returns_error_envelope(api_server: str):
    data = _get(f"{api_server}/missing")
    assert data["status"] == "error"
    assert data["errors"] == ["unknown local API route: GET /missing"]


def test_server_non_get_returns_405(api_server: str):
    req = urllib.request.Request(f"{api_server}/health", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 501


def test_server_doctor_returns_agents(api_server: str):
    data = _get(f"{api_server}/doctor")
    assert data["status"] == "ok"
    assert "agents" in data["data"]


def test_server_skills_returns_list(api_server: str):
    data = _get(f"{api_server}/skills")
    assert data["status"] == "ok"
    assert "skills" in data["data"]


def test_server_response_is_json_utf8(api_server: str):
    with urllib.request.urlopen(f"{api_server}/health") as resp:
        assert "application/json" in resp.headers.get("Content-Type", "")


def test_server_root_serves_dashboard_html(api_server: str):
    with urllib.request.urlopen(f"{api_server}/") as resp:
        content_type = resp.headers.get("Content-Type", "")
        assert "text/html" in content_type
        body = resp.read().decode("utf-8")
        assert "AgentMesh" in body
        assert "Dashboard" in body
        assert "/static/dashboard.css" in body
        assert "/static/dashboard.js" in body


def test_server_registry_status_returns_ok(api_server: str):
    data = _get(f"{api_server}/registry/status")
    assert data["schema"] == "agentmesh.local-api-response/v1"
    assert data["status"] == "ok"
    assert "skills_count" in data["data"]
    assert "agents_count" in data["data"]


def test_server_audit_summary_returns_ok(api_server: str):
    data = _get(f"{api_server}/audit/summary")
    assert data["status"] == "ok"
    assert "total_findings" in data["data"]
    assert "secrets" in data["data"]


def test_server_memory_status_returns_ok(api_server: str):
    data = _get(f"{api_server}/memory/status")
    assert data["status"] == "ok"
    assert "total_memories" in data["data"]


def test_server_model_status_returns_ok(api_server: str):
    data = _get(f"{api_server}/model/status")
    assert data["status"] == "ok"
    assert "total_configs" in data["data"]
