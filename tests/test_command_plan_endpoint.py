"""Phase B3 + B4: /commands/schemas (GET) and /commands/plan (POST).

These tests exercise the workstation-facing endpoints that let the front-end
render forms and preview assembled CLI commands without executing them.

Scope:

- GET /commands/schemas returns all registered schemas with ``v1`` envelopes.
- GET /commands/schemas/<id> returns a single schema; unknown id -> error.
- POST /commands/plan with ``{command_id, values}`` returns the assembled
  CLI command plus destructive / confirmation flags.
- Validation errors surface in ``errors`` without crashing the server.
- Unknown command_id returns 404.
- Missing ``command_id`` returns 400.
- Confirmation-required flag propagates to the UI.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from agentmesh.local_api.server import create_server


@pytest.fixture
def api_server(tmp_path):
    """Spin up the unified server on a random localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = create_server(host="127.0.0.1", port=port, registry=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── B3: /commands/schemas ────────────────────────────────────────────────


def test_commands_schemas_list_returns_all_registered(api_server):
    resp = _get_json(f"{api_server}/commands/schemas")
    assert resp["schema"] == "agentmesh.local-api-response/v1"
    assert resp["command"] == "local-api commands schemas"
    assert resp["status"] == "ok"
    data = resp["data"]
    assert data["total"] >= 15
    ids = {s["id"] for s in data["schemas"]}
    # Spot-check a few canonical ids.
    assert {"skills.sync", "skills.list", "init", "doctor", "audit.all"} <= ids
    assert "skills" in data["categories"]
    assert "core" in data["categories"]


def test_commands_schemas_detail_returns_single(api_server):
    resp = _get_json(f"{api_server}/commands/schemas/skills.sync")
    assert resp["status"] == "ok"
    data = resp["data"]
    assert data["id"] == "skills.sync"
    assert data["command"] == "am skills sync"
    assert data["schema"] == "agentmesh.command-schema/v1"
    assert data["destructive"] is True
    # Ensure params are declared as a list (not tuple) in JSON.
    assert isinstance(data["params"], list)
    # skills.sync should have a --to param.
    param_names = {p["name"] for p in data["params"]}
    assert "to" in param_names
    assert "dry_run" in param_names


def test_commands_schemas_detail_unknown_id_returns_error(api_server):
    resp = _get_json(f"{api_server}/commands/schemas/nope.garbage")
    assert resp["status"] == "error"
    assert any("unknown command schema" in e for e in resp["errors"])


def test_commands_schemas_survives_get_trailing_slash(api_server):
    # handle_readonly_request normalises trailing slashes.
    resp = _get_json(f"{api_server}/commands/schemas/")
    assert resp["status"] == "ok"
    assert resp["data"]["total"] >= 15


# ── B4: /commands/plan ───────────────────────────────────────────────────


def test_commands_plan_assembles_skills_sync_dry_run(api_server):
    resp = _post_json(
        f"{api_server}/commands/plan",
        {
            "command_id": "skills.sync",
            "values": {
                "to": ["hermes", "openclaw"],
                "dry_run": True,
                "mode": "copy",
                "json_output": True,
                "yes": True,
            },
        },
    )
    assert resp["status"] == "ok"
    data = resp["data"]
    assert data["command_id"] == "skills.sync"
    assert data["command"].startswith("am skills sync")
    assert "--to hermes,openclaw" in data["command"]
    assert "--dry-run" in data["command"]
    assert "--apply" not in data["command"]
    assert "--json" in data["command"]
    assert data["destructive"] is True
    assert data["confirmation_required"] is True
    # Destructive schemas produce a warning.
    assert any("destructive" in w.lower() for w in resp["warnings"])


def test_commands_plan_assembles_skills_scan_non_destructive(api_server):
    resp = _post_json(
        f"{api_server}/commands/plan",
        {
            "command_id": "skills.scan",
            "values": {"agent": "hermes", "json_output": True},
        },
    )
    assert resp["status"] == "ok"
    data = resp["data"]
    assert "am skills scan" in data["command"]
    assert "--agent hermes" in data["command"]
    assert data["destructive"] is False
    assert resp["warnings"] == []


def test_commands_plan_reports_validation_errors_without_crashing(api_server):
    """Missing required field should produce status=error but HTTP 200."""
    resp = _post_json(
        f"{api_server}/commands/plan",
        {"command_id": "skills.show", "values": {}},  # missing name
    )
    assert resp["status"] == "error"
    assert resp["errors"]
    assert "command_id" in resp["data"]


def test_commands_plan_rejects_bad_select_value(api_server):
    resp = _post_json(
        f"{api_server}/commands/plan",
        {"command_id": "skills.sync", "values": {"mode": "rsync"}},
    )
    assert resp["status"] == "error"
    assert any("invalid value" in e for e in resp["errors"])


def test_commands_plan_missing_command_id_returns_400(api_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post_json(f"{api_server}/commands/plan", {"values": {}})
    assert exc_info.value.code == 400


def test_commands_plan_non_dict_values_returns_400(api_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post_json(
            f"{api_server}/commands/plan",
            {"command_id": "skills.list", "values": ["not", "a", "dict"]},
        )
    assert exc_info.value.code == 400


def test_commands_plan_unknown_command_id_returns_404(api_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post_json(
            f"{api_server}/commands/plan",
            {"command_id": "does.not.exist", "values": {}},
        )
    assert exc_info.value.code == 404


def test_commands_plan_echoes_back_values_and_schema(api_server):
    resp = _post_json(
        f"{api_server}/commands/plan",
        {
            "command_id": "skills.enable",
            "values": {"name": "demo", "target": ["hermes"]},
        },
    )
    assert resp["status"] == "ok"
    data = resp["data"]
    assert data["values"] == {"name": "demo", "target": ["hermes"]}
    assert data["schema"]["id"] == "skills.enable"
    assert data["command"] == "am skills enable demo --target hermes"


def test_commands_plan_confirmation_flag_for_non_destructive(api_server):
    resp = _post_json(
        f"{api_server}/commands/plan",
        {"command_id": "skills.list", "values": {"json_output": True}},
    )
    assert resp["status"] == "ok"
    data = resp["data"]
    assert data["destructive"] is False
    assert data["confirmation_required"] is False
