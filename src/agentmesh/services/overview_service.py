from __future__ import annotations

from pathlib import Path

from agentmesh import __version__
from agentmesh.local_api.service import LOCAL_API_SCHEMA, READONLY_ENDPOINTS
from agentmesh.services.agent_service import adapter_capabilities_matrix, detect_agents
from agentmesh.services.runtime_service import LOAD_PLAN_SCHEMA


def build_local_overview(registry: Path | str) -> dict[str, object]:
    """Build a lightweight local-only AgentMesh status summary.

    This function performs no writes, starts no server, and intentionally reports
    unfinished Runtime/Web capabilities as unfinished.
    """

    registry_path = Path(registry)
    runtime_by_name = {info.name: info for info in detect_agents(Path.home())}
    agents = []
    for capability in adapter_capabilities_matrix(Path.home()):
        info = runtime_by_name[str(capability["name"])]
        agents.append(
            {
                "name": capability["name"],
                "installed": info.installed,
                "mode": capability["mode"],
                "writable": capability["writable"],
                "capabilities": capability["capabilities"],
                "safety_guards": capability["safety_guards"],
                "protected_paths": capability["protected_paths"],
                "warnings": list(info.warnings),
            }
        )

    codex = next(agent for agent in agents if agent["name"] == "codex")
    claude_code = next(agent for agent in agents if agent["name"] == "claude-code")

    return {
        "schema": "agentmesh.local-overview/v1",
        "version": __version__,
        "registry": str(registry_path),
        "local_first": True,
        "default_dry_run": True,
        "agents": agents,
        "local_api": {
            "contract_handler": "available",
            "response_schema": LOCAL_API_SCHEMA,
            "endpoints": [f"GET {path}" for path in READONLY_ENDPOINTS],
        },
        "network": {
            "http_server": "not implemented",
            "dashboard_ui": "not implemented",
            "default_bind": "none",
        },
        "runtime": {
            "load_plan_schema": LOAD_PLAN_SCHEMA,
            "auto_load": "alpha groundwork",
            "native_load_plan_consumption": "not implemented",
        },
        "safety": {
            "codex_system_protected": ".system" in codex["protected_paths"],
            "claude_code_auto_install": "no_auto_install" not in claude_code["safety_guards"],
            "claude_code_export_only": claude_code["mode"] == "export-only",
            "no_http_server_started": True,
            "no_dashboard_ui": True,
        },
    }


def local_overview_contract_snapshot(registry: Path | str) -> dict[str, object]:
    overview = build_local_overview(registry)
    agents = overview["agents"]
    return {
        "schema": "agentmesh.local-overview-contract-snapshot/v1",
        "overview_schema": overview["schema"],
        "top_level_keys": list(overview.keys()),
        "agent_names": sorted(agent["name"] for agent in agents),
        "agent_fields": sorted(agents[0].keys()) if agents else [],
        "local_api": overview["local_api"],
        "network": overview["network"],
        "runtime": overview["runtime"],
        "safety": overview["safety"],
        "mode_by_agent": {agent["name"]: agent["mode"] for agent in agents},
        "writable_by_agent": {agent["name"]: agent["writable"] for agent in agents},
        "protected_paths_by_agent": {agent["name"]: agent["protected_paths"] for agent in agents},
        "safety_guards_by_agent": {agent["name"]: agent["safety_guards"] for agent in agents},
    }
