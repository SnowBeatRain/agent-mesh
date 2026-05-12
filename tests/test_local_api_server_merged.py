"""Phase A2: 验证 server.py 与旧 server_advanced.py 合并后的行为。

关键点：
- 默认启动的 server 即提供完整功能（不再需要 --advanced）。
- POST /commands/execute 可执行 `am` CLI 命令并返回信封。
- POST /commands/history 可取回历史列表。
- POST /commands/favorites 支持 get/add/delete。
- POST 到未注册路径返回 501，不是 404 / 400。
- 旧的 server_advanced 模块已被删除（不可 import）。
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agentmesh.local_api.server import create_server


@pytest.fixture
def api_server(tmp_path: Path):
    """在随机端口启动合并后的 server。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = create_server(host="127.0.0.1", port=port, registry=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def _post_json(url: str, payload: dict, *, method: str = "POST") -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_post_to_unknown_endpoint_returns_501(api_server: str):
    """POST /health 等只读路径不接受 POST，应返回 501。"""
    req = urllib.request.Request(
        f"{api_server}/health",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 501


def test_post_commands_execute_rejects_non_am_command(api_server: str):
    """非 am/agentmesh 命令应被 command_service 拒绝。"""
    resp = _post_json(f"{api_server}/commands/execute", {"command": "ls -la"})
    assert resp["schema"] == "agentmesh.local-api-response/v1"
    assert resp["status"] == "error"
    assert "Only am and agentmesh commands are allowed" in (resp["errors"] or [""])[0]


def test_post_commands_execute_runs_am_version(api_server: str):
    """能安全执行 `am --version`（纯读取，不改 registry）。"""
    resp = _post_json(f"{api_server}/commands/execute", {"command": "am --version"})
    # 执行结果可能因 am 不在 PATH 而失败，但信封本身必须合法
    assert resp["schema"] == "agentmesh.local-api-response/v1"
    assert "executed" in resp["data"]


def test_post_commands_execute_missing_command_returns_error(api_server: str):
    resp_data = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(
        f"{api_server}/commands/execute",
        data=resp_data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


def test_post_commands_history_returns_envelope(api_server: str):
    """/commands/history 返回包含 history/total 的信封。"""
    resp = _post_json(f"{api_server}/commands/history", {})
    assert resp["schema"] == "agentmesh.local-api-response/v1"
    assert resp["status"] == "ok"
    assert "history" in resp["data"]
    assert "total" in resp["data"]


def test_post_commands_favorites_get_returns_envelope(api_server: str):
    """/commands/favorites action=get 返回 favorites list。"""
    resp = _post_json(f"{api_server}/commands/favorites", {"action": "get"})
    assert resp["schema"] == "agentmesh.local-api-response/v1"
    assert resp["status"] == "ok"
    assert "favorites" in resp["data"]


def test_post_commands_categories_returns_envelope(api_server: str):
    resp = _post_json(f"{api_server}/commands/categories", {})
    assert resp["schema"] == "agentmesh.local-api-response/v1"
    assert resp["status"] == "ok"
    assert "categories" in resp["data"]


def test_delete_unknown_endpoint_returns_501(api_server: str):
    req = urllib.request.Request(
        f"{api_server}/agents",
        data=b"{}",
        method="DELETE",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 501


def test_get_health_still_works_after_merge(api_server: str):
    """合并后原有 GET /health 契约不破。"""
    with urllib.request.urlopen(f"{api_server}/health") as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert data["schema"] == "agentmesh.local-api-response/v1"
    assert data["status"] == "ok"


def test_server_advanced_module_removed():
    """旧 server_advanced 模块已被删除，不应能 import。"""
    with pytest.raises(ImportError):
        import agentmesh.local_api.server_advanced  # noqa: F401


def test_batch_plan_returns_envelope(api_server: str):
    resp = _post_json(
        f"{api_server}/commands/batch/plan",
        {"commands": ["am --version", "am doctor"], "targets": ["hermes"]},
    )
    assert resp["schema"] == "agentmesh.local-api-response/v1"
    assert resp["status"] == "ok"
    # CommandExecutor.get_batch_execution_plan returns {"success": True, "plan": {...}}
    data = resp["data"]
    assert data.get("success") is True
    assert "plan" in data
    assert data["plan"]["total_commands"] == 2
