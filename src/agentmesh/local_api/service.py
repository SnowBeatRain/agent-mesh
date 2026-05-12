from __future__ import annotations

from pathlib import Path

from agentmesh.audit.engine import AuditEngine
from agentmesh.config import loader
from agentmesh.config.loader import registry_skills_root, resolve_agentmesh_home
from agentmesh.policy.service import evaluate_findings
from agentmesh.services.agent_service import adapter_capabilities_matrix, detect_agents
from agentmesh.services.backup_service import list_backup_records
from agentmesh.services.memory_service import list_imported_memories
from agentmesh.services.model_service import diff_configs, scan_all
from agentmesh.services.registry_service import list_registry_skills
from agentmesh.services.runtime_service import bootstrap_status
from agentmesh.services.sync_service import list_sync_history

LOCAL_API_SCHEMA = "agentmesh.local-api-response/v1"
LOCAL_API_CONTRACT_SNAPSHOT_SCHEMA = "agentmesh.local-api-contract-snapshot/v1"
READONLY_ENDPOINTS = (
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
    # Phase B3: list of all registered command schemas for the workstation.
    "/commands/schemas",
    # Phase B5: recipes (operation cookbooks) the workstation renders.
    "/recipes",
)

# Phase A5 + B3: parameterized read-only endpoints. These are NOT in the fixed
# contract snapshot because they require an id / name at the end of the URL.
# They are documented here so front-ends know to expect them:
#
#   GET /skills/<name>                      → full registry-skill detail
#   GET /skills/<name>?targets=a,b          → detail + per-target diff levels
#   GET /skills/diff/<name>?target=<agent>  → structured unified diff (hunks)
#   GET /commands/schemas/<command_id>      → one CommandSchema (v1 envelope)
#   GET /recipes/<recipe_id>                → one Recipe with full steps
PARAMETERIZED_READONLY_ENDPOINTS = (
    "/skills/<name>",
    "/skills/diff/<name>",
    "/commands/schemas/<command_id>",
    "/recipes/<recipe_id>",
)
READONLY_METHODS = {"GET"}


def _redact_path(path_str: str, home: Path) -> str:
    """Replace the absolute home prefix with ~ for path redaction."""
    try:
        path_obj = Path(path_str)
        if path_obj == home:
            return "~"
        try:
            relative = path_obj.relative_to(home)
            return "~" + "/" + str(relative).replace("\\", "/")
        except ValueError:
            # path_obj is not relative to home
            return path_str
    except Exception:
        # Fallback to original string if path parsing fails
        return path_str


def _redact_paths_in_value(value: object, home: Path) -> object:
    """Recursively redact absolute home paths in a nested dict/list structure."""
    if isinstance(value, str):
        return _redact_path(value, home)
    if isinstance(value, dict):
        return {k: _redact_paths_in_value(v, home) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_paths_in_value(item, home) for item in value]
    return value


def _response(
    *,
    command: str,
    status: str,
    data: dict | list | None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> dict:
    return {
        "schema": LOCAL_API_SCHEMA,
        "command": command,
        "status": status,
        "data": data,
        "warnings": warnings or [],
        "errors": errors or [],
        "next_steps": next_steps or [],
    }


def _agents_payload() -> dict:
    home = loader.user_home()
    runtime_by_name = {info.name: info for info in detect_agents(home)}
    agents = []
    for capability in adapter_capabilities_matrix(home):
        info = runtime_by_name[str(capability["name"])]
        agents.append(
            {
                **capability,
                "installed": info.installed,
                "warnings": list(info.warnings),
            }
        )
    return {"agents": agents}


def handle_readonly_request(method: str, path: str, registry: str | Path | None = None) -> dict:
    """Handle an AgentMesh Local API alpha request without starting a server.

    This is the read-only contract layer that a future local HTTP server or dashboard
    can call. It intentionally performs no writes and exposes only GET endpoints.
    """

    normalized_method = method.upper()
    normalized_path = path.rstrip("/") or "/"
    home = resolve_agentmesh_home(str(registry) if registry is not None else None)
    user_home = loader.user_home()

    if normalized_method not in READONLY_METHODS:
        return _response(
            command="local-api blocked",
            status="blocked",
            data={"method": normalized_method, "path": normalized_path},
            errors=[f"local API alpha is read-only; {normalized_method} is not allowed"],
            next_steps=["Use GET endpoints or the CLI for explicit write operations."],
        )

    resp: dict | None = None

    if normalized_path == "/health":
        resp = _response(
            command="local-api health",
            status="ok",
            data={
                "service": "agentmesh-local-api",
                "mode": "read-only",
                "registry": str(home),
            },
        )

    elif normalized_path == "/agents":
        resp = _response(
            command="local-api agents list",
            status="ok",
            data=_agents_payload(),
        )

    elif normalized_path == "/doctor":
        agents = _agents_payload()["agents"]
        resp = _response(
            command="local-api doctor",
            status="ok",
            data={
                "registry": str(home),
                "agents": agents,
            },
        )

    elif normalized_path == "/overview":
        from agentmesh.services.overview_service import build_local_overview

        resp = _response(
            command="local-api overview",
            status="ok",
            data=build_local_overview(home),
        )

    elif normalized_path == "/skills":
        resp = _response(
            command="local-api skills list",
            status="ok",
            data={"skills": [p.name for p in list_registry_skills(home)]},
        )

    elif normalized_path == "/history":
        resp = _response(
            command="local-api history list",
            status="ok",
            data={"entries": list_sync_history(home)},
        )

    elif normalized_path == "/backups":
        backup_payload = list_backup_records(home)
        resp = _response(
            command="local-api backup list",
            status="ok",
            data=backup_payload["data"],
            warnings=backup_payload.get("warnings", []),
            errors=backup_payload.get("errors", []),
            next_steps=backup_payload.get("next_steps", []),
        )

    elif normalized_path == "/runtime/status":
        runtime_result, runtime_warnings = bootstrap_status(home, "hermes")
        status = "installed" if runtime_result.get("installed") else "not-installed"
        resp = _response(
            command="local-api runtime status",
            status=status,
            data={"target": "hermes", **runtime_result},
            warnings=runtime_warnings,
        )
    elif normalized_path == "/registry/status":
        skills_paths = list_registry_skills(home)
        agents = _agents_payload()["agents"]
        installed_agents = [a for a in agents if a.get("installed")]
        history = list_sync_history(home)
        last_sync = history[-1].get("timestamp", "") if history else ""
        resp = _response(
            command="local-api registry status",
            status="ok",
            data={
                "skills_count": len(skills_paths),
                "agents_count": len(installed_agents),
                "total_agents": len(agents),
                "last_sync": last_sync,
                "skills": [p.name for p in skills_paths],
            },
        )

    elif normalized_path == "/audit/summary":
        skills_root = registry_skills_root(home)
        findings = AuditEngine().audit_path(skills_root)
        policy = evaluate_findings(skills_root, findings)
        by_kind: dict[str, int] = {}
        for f in findings:
            by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        resp = _response(
            command="local-api audit summary",
            status="ok",
            data={
                "total_findings": len(findings),
                "secrets": by_kind.get("secret", 0),
                "dangerous_scripts": by_kind.get("dangerous-script", 0),
                "platform_refs": by_kind.get("platform-ref", 0),
                "allowed": policy.allowed,
                "blocked_count": policy.blocked_count,
                "warning_count": policy.warning_count,
                "info_count": policy.info_count,
            },
        )

    elif normalized_path == "/memory/status":
        memories = list_imported_memories(home)
        by_agent: dict[str, int] = {}
        for m in memories:
            by_agent[m["agent"]] = by_agent.get(m["agent"], 0) + 1
        resp = _response(
            command="local-api memory status",
            status="ok",
            data={
                "total_memories": len(memories),
                "by_agent": by_agent,
                "memories": memories,
            },
        )

    elif normalized_path == "/model/status":
        configs = scan_all(user_home)
        model_diffs = diff_configs(user_home)
        resp = _response(
            command="local-api model status",
            status="ok",
            data={
                "total_configs": len(configs),
                "configs": [c.to_dict() for c in configs],
                "diffs": [d.to_dict() for d in model_diffs],
            },
        )

    elif normalized_path == "/plans/preview":
        # Generate sync plan preview for interactive UI
        from agentmesh.services.sync_service import render_sync_plan
        # Default to all installed agents for preview
        agents = _agents_payload()["agents"]
        installed_targets = [a["name"] for a in agents if a.get("installed")]
        if installed_targets:
            plan = render_sync_plan(home, installed_targets, mode="PREVIEW")
            resp = _response(
                command="local-api plans preview",
                status="ok",
                data=plan,
            )
        else:
            resp = _response(
                command="local-api plans preview",
                status="ok",
                data={"mode": "PREVIEW", "summary": {"actions": 0, "allowed": 0, "blocked": 0, "warnings": 0}, "actions": []},
                warnings=["No installed agents found for sync preview"],
            )

    elif normalized_path == "/assets/list":
        # List all assets in registry with metadata
        skills = list_registry_skills(home)
        assets = []
        for skill_path in skills:
            skill_dir = registry_skills_root(home) / skill_path.name
            manifest_path = skill_dir / "SKILL.md"
            if manifest_path.exists():
                # Simple metadata extraction - could be enhanced
                assets.append({
                    "name": skill_path.name,
                    "type": "skill",
                    "path": str(skill_dir),
                    "has_manifest": True,
                })
            else:
                assets.append({
                    "name": skill_path.name,
                    "type": "skill",
                    "path": str(skill_dir),
                    "has_manifest": False,
                })

        resp = _response(
            command="local-api assets list",
            status="ok",
            data={"assets": assets, "total": len(assets)},
        )

    elif normalized_path.startswith("/assets/detail/"):
        # Get detailed information about a specific asset
        asset_name = normalized_path[len("/assets/detail/"):]
        skill_dir = registry_skills_root(home) / asset_name
        if skill_dir.exists():
            manifest_path = skill_dir / "SKILL.md"
            manifest_content = None
            if manifest_path.exists():
                manifest_content = manifest_path.read_text(encoding="utf-8")

            # Get audit information for this asset
            findings = AuditEngine().audit_path(skill_dir)
            policy = evaluate_findings(skill_dir, findings)

            resp = _response(
                command="local-api assets detail",
                status="ok",
                data={
                    "name": asset_name,
                    "type": "skill",
                    "path": str(skill_dir),
                    "manifest": manifest_content,
                    "audit": {
                        "total_findings": len(findings),
                        "allowed": policy.allowed,
                        "blocked_count": policy.blocked_count,
                        "warning_count": policy.warning_count,
                        "findings": [f.to_dict() for f in findings],
                    },
                },
            )
        else:
            resp = _response(
                command="local-api assets detail",
                status="error",
                data={"name": asset_name},
                errors=[f"Asset not found: {asset_name}"],
            )

    # Phase B3: /commands/schemas lists every registered CommandSchema; the
    # workstation uses this to render parameter forms without round-tripping
    # through the CLI. /commands/schemas/<id> returns one schema.
    elif normalized_path == "/commands/schemas":
        from agentmesh.local_api.schemas import list_schemas

        schemas = [s.to_dict() for s in list_schemas()]
        resp = _response(
            command="local-api commands schemas",
            status="ok",
            data={
                "schemas": schemas,
                "total": len(schemas),
                "categories": sorted({s["category"] for s in schemas}),
            },
            next_steps=[
                "POST /commands/plan with {command_id, values} to preview a CLI string.",
                "POST /commands/execute to actually run an assembled command.",
            ],
        )

    elif normalized_path.startswith("/commands/schemas/"):
        from agentmesh.local_api.schemas import get_schema

        command_id = normalized_path[len("/commands/schemas/") :].strip("/")
        schema = get_schema(command_id)
        if schema is None:
            resp = _response(
                command="local-api commands schemas",
                status="error",
                data={"command_id": command_id},
                errors=[f"unknown command schema: {command_id}"],
                next_steps=[
                    "GET /commands/schemas to list available command ids.",
                ],
            )
        else:
            resp = _response(
                command="local-api commands schemas",
                status="ok",
                data=schema.to_dict(),
            )

    # Phase B5: /recipes lists built-in Recipe summaries; /recipes/<id>
    # returns one recipe with full steps.
    elif normalized_path == "/recipes":
        from agentmesh.local_api.recipes import list_recipes

        recipes = [r.to_dict(include_steps=False) for r in list_recipes()]
        resp = _response(
            command="local-api recipes list",
            status="ok",
            data={
                "recipes": recipes,
                "total": len(recipes),
                "difficulties": sorted({r["difficulty"] for r in recipes}),
            },
            next_steps=[
                "GET /recipes/<id> for the full step list.",
                "POST /recipes/<id>/preview with {overrides} to assemble commands.",
            ],
        )

    elif normalized_path.startswith("/recipes/"):
        from agentmesh.local_api.recipes import get_recipe

        recipe_id = normalized_path[len("/recipes/") :].strip("/")
        recipe = get_recipe(recipe_id)
        if recipe is None:
            resp = _response(
                command="local-api recipes detail",
                status="error",
                data={"recipe_id": recipe_id},
                errors=[f"unknown recipe: {recipe_id}"],
                next_steps=["GET /recipes to list available recipes."],
            )
        else:
            resp = _response(
                command="local-api recipes detail",
                status="ok",
                data=recipe.to_dict(include_steps=True),
                next_steps=[
                    "POST /recipes/{id}/preview to assemble command strings.",
                ],
            )

    # Phase A5: /skills/<name> returns the detailed description used by the
    # workstation UI (file_count, enabled_targets, risk_summary, last_diff …).
    elif normalized_path.startswith("/skills/") and not normalized_path.startswith(
        "/skills/diff/"
    ):
        from agentmesh.services.registry_service import describe_registry_skill_detailed

        remainder = normalized_path[len("/skills/") :]
        # Parse optional diff_targets query hint embedded as /skills/<name>?targets=a,b
        # (handle_readonly_request receives the already-parsed path, so we split on "?").
        if "?" in remainder:
            name_part, _, query = remainder.partition("?")
        else:
            name_part, query = remainder, ""
        skill_name = name_part.strip("/")
        diff_targets: list[str] = []
        if query:
            for piece in query.split("&"):
                if piece.startswith("targets="):
                    diff_targets = [
                        t.strip() for t in piece[len("targets=") :].split(",") if t.strip()
                    ]
                    break
        try:
            detail = describe_registry_skill_detailed(
                home, skill_name, with_diff_targets=diff_targets or None
            )
            resp = _response(
                command="local-api skills detail",
                status="ok",
                data=detail,
            )
        except FileNotFoundError as exc:
            resp = _response(
                command="local-api skills detail",
                status="error",
                data={"skill": skill_name},
                errors=[str(exc)],
                next_steps=[
                    "Run `agentmesh skills list --json` to see available registry skills."
                ],
            )

    # Phase A5: /skills/diff/<name>?target=<agent> returns structured diff
    # (unified hunks per file) for the workstation diff view.
    elif normalized_path.startswith("/skills/diff/"):
        from agentmesh.engine.diff_engine import diff_skill_detailed

        remainder = normalized_path[len("/skills/diff/") :]
        if "?" in remainder:
            name_part, _, query = remainder.partition("?")
        else:
            name_part, query = remainder, ""
        skill_name = name_part.strip("/")
        target = ""
        if query:
            for piece in query.split("&"):
                if piece.startswith("target="):
                    target = piece[len("target=") :].strip()
                    break
        if not target:
            resp = _response(
                command="local-api skills diff",
                status="error",
                data={"skill": skill_name},
                errors=["missing query parameter: target"],
                next_steps=[
                    "Append ?target=<agent> to the URL, e.g. /skills/diff/demo?target=hermes."
                ],
            )
        else:
            try:
                data = diff_skill_detailed(home, skill_name, target)
                resp = _response(
                    command="local-api skills diff",
                    status="ok",
                    data=data,
                )
            except (FileNotFoundError, ValueError) as exc:
                resp = _response(
                    command="local-api skills diff",
                    status="error",
                    data={"skill": skill_name, "target": target},
                    errors=[str(exc)],
                    next_steps=[
                        "Use `agentmesh agents list --json` to see supported targets.",
                    ],
                )

    else:
        resp = _response(
            command="local-api unknown",
            status="error",
            data={"method": normalized_method, "path": normalized_path},
            errors=[f"unknown local API route: {normalized_method} {normalized_path}"],
            next_steps=["Use GET /health, GET /doctor, or GET /agents."],
        )

    # Apply path redaction to all data fields before returning
    resp["data"] = _redact_paths_in_value(resp["data"], user_home)
    return resp


def _endpoint_snapshot(path: str, response: dict) -> dict:
    item: dict[str, object] = {
        "method": "GET",
        "path": path,
        "response_schema": response["schema"],
        "command": response["command"],
        "status": response["status"],
        "envelope_keys": list(response.keys()),
        "data_keys": sorted(response["data"].keys())
        if isinstance(response.get("data"), dict)
        else [],
    }
    if path == "/agents":
        agents = response["data"]["agents"]
        item["agent_names"] = sorted(agent["name"] for agent in agents)
        item["safety_fields"] = [
            "capabilities",
            "mode",
            "protected_paths",
            "safety_guards",
            "writable",
        ]
        item["protected_paths_by_agent"] = {
            agent["name"]: agent["protected_paths"] for agent in agents
        }
        item["mode_by_agent"] = {agent["name"]: agent["mode"] for agent in agents}
        item["capabilities_by_agent"] = {agent["name"]: agent["capabilities"] for agent in agents}
        item["safety_guards_by_agent"] = {agent["name"]: agent["safety_guards"] for agent in agents}
        item["writable_by_agent"] = {agent["name"]: agent["writable"] for agent in agents}
    return item


def local_api_contract_snapshot(registry: str | Path | None = None) -> dict:
    endpoints = [
        _endpoint_snapshot(path, handle_readonly_request("GET", path, registry=registry))
        for path in READONLY_ENDPOINTS
    ]
    return {
        "schema": LOCAL_API_CONTRACT_SNAPSHOT_SCHEMA,
        "summary": {"endpoints": len(endpoints), "read_only": True},
        "endpoints": endpoints,
    }
