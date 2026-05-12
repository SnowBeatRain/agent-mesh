from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agentmesh.policy.service import evaluate_findings
from agentmesh.services.registry_service import list_registry_skills
from agentmesh.utils.yaml_io import read_yaml, write_yaml
from agentmesh.validation.native import validate_native_runtime
from agentmesh.validation.skills import validate_registry_skills

RUNTIME_AUDIT_SCHEMA = "agentmesh.runtime-audit/v1"
LOADER_NAME = "agentmesh-loader"
RUNTIME_TARGETS = {
    "hermes": (".hermes", "skills", "custom"),
    "openclaw": (".openclaw", "workspace", "skills"),
    "codex": (".codex", "skills"),
    "cursor": (".cursor", "rules"),
    "windsurf": (".windsurf", "rules"),
}

AUTO_LOAD_HOOK_NAME = "agentmesh-auto-load.sh"


class RuntimeBootstrapBlocked(RuntimeError):
    """Raised when bootstrap shim cannot be safely written."""


class RuntimeLoadPlanError(RuntimeError):
    """Raised when a runtime LoadPlan cannot be read or validated."""


LOAD_PLAN_SCHEMA = "agentmesh.runtime-load-plan/v1"


def _validate_load_plan_schema(load_plan: dict) -> None:
    schema = load_plan.get("schema")
    if schema != LOAD_PLAN_SCHEMA:
        raise RuntimeLoadPlanError(f"unsupported load plan schema: {schema}")


def build_runtime_load_plan(agentmesh_home: Path, target: str) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    load_plan_path = agentmesh_home / "state" / "runtime-load-plans" / f"{target}.json"
    plan_id = (
        "rtlp-"
        + hashlib.sha256(f"{target}\0{agentmesh_home}\0{generated_at}".encode()).hexdigest()[:12]
    )
    skills = []
    for skill_dir in list_registry_skills(agentmesh_home):
        policy = evaluate_findings(skill_dir).to_dict()
        blocked_reasons = [] if policy["allowed"] else ["policy:block"]
        skills.append(
            {
                "name": skill_dir.name,
                "decision": "allow" if policy["allowed"] else "block",
                "blocked_reasons": blocked_reasons,
            }
        )
    blocked = [item for item in skills if item["decision"] == "block"]
    return {
        "schema": LOAD_PLAN_SCHEMA,
        "plan_id": plan_id,
        "generated_at": generated_at,
        "load_plan_path": str(load_plan_path),
        "target": target,
        "registry": str(agentmesh_home / "registry"),
        "mode": "direct-registry-read",
        "summary": {
            "skills": len(skills),
            "allowed": len(skills) - len(blocked),
            "blocked": len(blocked),
        },
        "skills": skills,
    }


def persist_runtime_load_plan(agentmesh_home: Path, target: str) -> dict:
    load_plan = build_runtime_load_plan(agentmesh_home, target)
    load_plan_path = Path(load_plan["load_plan_path"])
    load_plan_path.parent.mkdir(parents=True, exist_ok=True)
    load_plan_path.write_text(
        json.dumps(load_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return load_plan


def build_runtime_env(agentmesh_home: Path, target: str) -> str:
    load_plan_path = agentmesh_home / "state" / "runtime-load-plans" / f"{target}.json"
    return "\n".join(
        [
            f"AGENTMESH_HOME='{agentmesh_home}'",
            f"AGENTMESH_REGISTRY='{agentmesh_home / 'registry'}'",
            f"AGENTMESH_TARGET='{target}'",
            f"AGENTMESH_LOAD_PLAN='{load_plan_path}'",
        ]
    )


def build_runtime_exec_plan(load_plan: dict) -> dict:
    actions = []
    for skill in load_plan.get("skills", []):
        decision = skill.get("decision")
        actions.append(
            {
                "action": "load-skill" if decision == "allow" else "block-skill",
                "name": skill.get("name"),
                "decision": decision,
            }
        )
    return {
        "target": load_plan.get("target"),
        "mode": "plan-reader-dry-run",
        "summary": load_plan.get("summary", {}),
        "actions": actions,
    }


def load_runtime_exec_plan(load_plan_path: Path) -> dict:
    load_plan = json.loads(load_plan_path.read_text(encoding="utf-8"))
    _validate_load_plan_schema(load_plan)
    return build_runtime_exec_plan(load_plan)


def detect_load_plan_staleness(agentmesh_home: Path, load_plan_path: Path) -> dict:
    """Compare persisted LoadPlan skill list against current registry.

    Returns a dict with keys:
      - stale (bool): True if any structural or content change detected.
      - skills_added (list[str]): skill names in registry but not in LoadPlan.
      - skills_removed (list[str]): skill names in LoadPlan but not in registry.
      - content_changed (list[str]): skill names whose files are newer than LoadPlan.
      - error (str | None): error message if LoadPlan could not be read.
    """
    result: dict = {
        "stale": False,
        "skills_added": [],
        "skills_removed": [],
        "content_changed": [],
        "error": None,
    }
    if not load_plan_path.exists():
        result["error"] = f"LoadPlan not found: {load_plan_path}"
        return result

    try:
        load_plan = json.loads(load_plan_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result["error"] = f"Failed to read LoadPlan: {exc}"
        return result

    _validate_load_plan_schema(load_plan)

    plan_skill_names = {
        s["name"] for s in load_plan.get("skills", []) if s.get("decision") == "allow"
    }
    current_skill_dirs = list_registry_skills(agentmesh_home)
    current_skill_names = {d.name for d in current_skill_dirs}

    # Structural diff
    result["skills_added"] = sorted(current_skill_names - plan_skill_names)
    result["skills_removed"] = sorted(plan_skill_names - current_skill_names)

    # Content change detection (mtime-based)
    plan_mtime = load_plan_path.stat().st_mtime
    for skill_dir in current_skill_dirs:
        for f in skill_dir.rglob("*"):
            if f.is_file() and f.stat().st_mtime > plan_mtime:
                result["content_changed"].append(skill_dir.name)
                break

    result["stale"] = bool(
        result["skills_added"] or result["skills_removed"] or result["content_changed"]
    )
    return result


def _rendered_file_for_target(target: str, home: Path | None = None) -> Path | None:
    """Return the expected rendered file path for a bootstrapped target."""
    from agentmesh.runtime.renderer import get_renderer

    loader = loader_path(target, home)
    renderer = get_renderer(target)
    if renderer:
        return renderer.entrypoint_path(loader)
    # Fallback: SKILL.md inside loader dir
    return loader / "SKILL.md"


def validate_runtime(agentmesh_home: Path, target: str) -> dict:
    report = validate_registry_skills(agentmesh_home, target)
    report["native_validation"] = validate_native_runtime(target, agentmesh_home)
    if report["native_validation"]["status"] == "failed":
        report["ok"] = False
    return report


def _target_skill_root(target: str, home: Path | None = None) -> Path:
    if target not in RUNTIME_TARGETS:
        raise ValueError(f"暂不支持 runtime bootstrap 目标：{target}")
    return (home or Path.home()).joinpath(*RUNTIME_TARGETS[target])


def loader_path(target: str, home: Path | None = None) -> Path:
    return _target_skill_root(target, home) / LOADER_NAME


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def build_runtime_response(
    schema: str,
    command: str,
    status: str,
    data: dict,
    *,
    dry_run: bool | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> dict:
    response = {
        "schema": schema,
        "command": command,
        "status": status,
        "data": data,
        "warnings": warnings or [],
        "errors": errors or [],
        "next_steps": next_steps or [],
    }
    if dry_run is not None:
        response["dry_run"] = dry_run
    return response


def build_bootstrap_plan(agentmesh_home: Path, target: str, home: Path | None = None) -> dict:
    load_plan = build_runtime_load_plan(agentmesh_home, target)
    loader = loader_path(target, home)
    installed = loader.exists()
    managed = (loader / "agentmesh-loader.yaml").exists()
    return {
        "target": target,
        "mode": "bootstrap-shim",
        "loader_path": str(loader),
        "registry": str(agentmesh_home / "registry"),
        "installed": installed,
        "managed": managed,
        "summary": load_plan["summary"],
        "actions": []
        if installed and managed
        else [
            {
                "action": "create",
                "path": str(loader),
                "description": "create AgentMesh bootstrap loader shim",
            }
        ],
    }


def bootstrap_status(
    agentmesh_home: Path, target: str, home: Path | None = None
) -> tuple[dict, list[str]]:
    loader = loader_path(target, home)
    manifest = loader / "agentmesh-loader.yaml"
    data = read_yaml(manifest) if manifest.exists() else {}
    warnings: list[str] = []

    load_plan_path_str = data.get("load_plan_path")
    stale_details: dict | None = None

    if load_plan_path_str:
        load_plan_path = Path(load_plan_path_str)
        if load_plan_path.exists():
            stale_details = detect_load_plan_staleness(agentmesh_home, load_plan_path)
            if stale_details.get("error"):
                warnings.append(stale_details["error"])
            else:
                # Build human-readable warnings from stale_details
                if stale_details.get("skills_added"):
                    warnings.append(
                        f"LoadPlan is stale: new skills in registry not in LoadPlan: "
                        f"{', '.join(stale_details['skills_added'])}. "
                        f"Run 'agentmesh runtime update --target {target}' to refresh."
                    )
                if stale_details.get("skills_removed"):
                    warnings.append(
                        f"LoadPlan is stale: skills in LoadPlan no longer in registry: "
                        f"{', '.join(stale_details['skills_removed'])}. "
                        f"Run 'agentmesh runtime update --target {target}' to refresh."
                    )
                if stale_details.get("content_changed"):
                    warnings.append(
                        f"LoadPlan is stale: skill content modified since LoadPlan: "
                        f"{', '.join(stale_details['content_changed'])}. "
                        f"Run 'agentmesh runtime update --target {target}' to refresh."
                    )
        elif load_plan_path_str:
            msg = (
                "LoadPlan file referenced by manifest does not exist: "
                f"{load_plan_path_str}. "
                f"Run 'agentmesh runtime update --target {target}' "
                "to regenerate."
            )
            warnings.append(msg)
            stale_details = {
                "stale": True,
                "skills_added": [],
                "skills_removed": [],
                "content_changed": [],
                "error": f"LoadPlan file not found: {load_plan_path_str}",
            }

    # Check rendered file
    rendered_path = _rendered_file_for_target(target, home)
    rendered_exists = rendered_path.exists() if rendered_path else False
    if loader.exists() and data.get("managed") and not rendered_exists:
        warnings.append(
            f"Rendered file missing: {rendered_path}. "
            f"Run 'agentmesh runtime update --target {target}' to regenerate."
        )

    plan_stale = stale_details["stale"] if stale_details else False

    return {
        "target": target,
        "loader_path": str(loader),
        "installed": loader.exists(),
        "managed": manifest.exists(),
        "load_plan_path": load_plan_path_str,
        "load_plan_schema": data.get("load_plan_schema"),
        "entrypoint": data.get("entrypoint"),
        "plan_stale": plan_stale,
        "stale_details": stale_details,
        "rendered_file_path": str(rendered_path) if rendered_path else None,
        "rendered_file_exists": rendered_exists,
    }, warnings


def apply_bootstrap(agentmesh_home: Path, target: str, home: Path | None = None) -> dict:
    from agentmesh.runtime.renderer import get_renderer

    plan = build_bootstrap_plan(agentmesh_home, target, home)
    loader = Path(plan["loader_path"])
    manifest = loader / "agentmesh-loader.yaml"
    if loader.exists() and not manifest.exists():
        raise RuntimeBootstrapBlocked("target loader path exists but is not managed by AgentMesh")
    loader.mkdir(parents=True, exist_ok=True)
    load_plan = persist_runtime_load_plan(agentmesh_home, target)
    load_plan_path = Path(load_plan["load_plan_path"])

    # Collect allowed skill names for rendering
    allowed_skills = [
        s["name"] for s in load_plan.get("skills", []) if s.get("decision") == "allow"
    ]
    blocked_count = len(load_plan.get("skills", [])) - len(allowed_skills)
    metadata = {
        "plan_id": load_plan["plan_id"],
        "generated_at": load_plan["generated_at"],
        "target": target,
        "registry": str(agentmesh_home / "registry"),
        "blocked": blocked_count,
        "loader_dir": str(loader),
        "rules_dir": str(loader.parent),
    }

    # Use renderer to generate native format content
    renderer = get_renderer(target)
    if renderer:
        payloads = renderer.render(agentmesh_home, allowed_skills, metadata)
        for payload in payloads:
            payload.path.parent.mkdir(parents=True, exist_ok=True)
            payload.path.write_text(payload.content, encoding="utf-8")
    else:
        # Fallback: static shim for targets without a renderer (codex, claude-code)
        (loader / "SKILL.md").write_text(
            "---\n"
            f"name: {LOADER_NAME}\n"
            "description: AgentMesh shared registry loader shim.\n"
            "---\n\n"
            "# AgentMesh Loader\n\n"
            "This lightweight shim points this runtime to the local AgentMesh registry.\n"
            "It does not contain copied shared skills or secrets.\n",
            encoding="utf-8",
        )

    # Write env and entrypoint
    entrypoint = loader / "agentmesh_loader.py"
    (loader / "agentmesh.env").write_text(
        build_runtime_env(agentmesh_home, target)
        + "\n"
        + f"AGENTMESH_LOADER_ENTRYPOINT='{entrypoint}'\n",
        encoding="utf-8",
    )
    entrypoint.write_text(
        "#!/usr/bin/env python3\n"
        '"""AgentMesh runtime LoadPlan reader shim."""\n'
        "from __future__ import annotations\n\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n\n"
        "LOAD_PLAN_SCHEMA = 'agentmesh.runtime-load-plan/v1'\n\n"
        "def read_load_plan(path: str | None = None) -> dict:\n"
        "    load_plan_path = Path(path or os.environ['AGENTMESH_LOAD_PLAN'])\n"
        "    plan = json.loads(load_plan_path.read_text(encoding='utf-8'))\n"
        "    if plan.get('schema') != LOAD_PLAN_SCHEMA:\n"
        "        raise ValueError(f'unsupported load plan schema: {plan.get(\"schema\")}')\n"
        "    return plan\n\n"
        "def build_actions(plan: dict) -> list[dict]:\n"
        "    actions = []\n"
        "    for skill in plan.get('skills', []):\n"
        "        decision = skill.get('decision')\n"
        "        actions.append({\n"
        "            'action': 'load-skill' if decision == 'allow' else 'block-skill',\n"
        "            'name': skill.get('name'),\n"
        "            'decision': decision,\n"
        "        })\n"
        "    return actions\n\n"
        "def main() -> None:\n"
        "    plan = read_load_plan()\n"
        "    payload = {'schema': LOAD_PLAN_SCHEMA, 'actions': build_actions(plan)}\n"
        "    print(json.dumps(payload, ensure_ascii=False))\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    write_yaml(
        manifest,
        {
            "schema": "agentmesh.bootstrap-shim/v1",
            "target": target,
            "registry": str(agentmesh_home / "registry"),
            "mode": "registry-reference",
            "managed": True,
            "created_by": "agentmesh",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "load_plan_path": str(load_plan_path),
            "load_plan_schema": "agentmesh.runtime-load-plan/v1",
            "entrypoint": "agentmesh_loader.py",
        },
    )
    plan["load_plan_path"] = str(load_plan_path)
    plan["load_plan_schema"] = "agentmesh.runtime-load-plan/v1"
    plan["entrypoint"] = str(entrypoint)
    plan["applied"] = True
    plan["rendered_skills"] = len(allowed_skills)

    # Install auto-load hook
    hook_path = install_auto_load_hook(agentmesh_home, target, home)
    plan["hook_path"] = str(hook_path)

    _write_runtime_audit(
        agentmesh_home,
        target,
        "bootstrap",
        plan_id=load_plan["plan_id"],
        allowed=allowed_skills,
        blocked_count=blocked_count,
    )
    return plan


def disable_bootstrap(
    agentmesh_home: Path, target: str, apply: bool = False, home: Path | None = None
) -> dict:
    _ = agentmesh_home
    loader = loader_path(target, home)
    manifest = loader / "agentmesh-loader.yaml"
    result = {
        "target": target,
        "loader_path": str(loader),
        "installed": loader.exists(),
        "managed": manifest.exists(),
        "mode": "APPLY" if apply else "DRY-RUN",
    }
    if apply and loader.exists():
        if not manifest.exists():
            raise RuntimeBootstrapBlocked(
                "target loader path exists but is not managed by AgentMesh"
            )
        backup = loader.parent / f".{LOADER_NAME}.disabled-{_timestamp()}"
        shutil.move(str(loader), str(backup))
        result["backup"] = str(backup)
        result["installed"] = False

        # Uninstall auto-load hook
        hook_removed = uninstall_auto_load_hook(target, home)
        result["hook_removed"] = hook_removed

        _write_runtime_audit(
            agentmesh_home,
            target,
            "disable",
            plan_id=None,
            allowed=[],
            blocked_count=0,
        )
    return result


def _write_runtime_audit(
    agentmesh_home: Path,
    target: str,
    action: str,
    *,
    plan_id: str | None,
    allowed: list[str],
    blocked_count: int,
) -> Path:
    """Write an audit record for a runtime operation."""
    audit_dir = agentmesh_home / "state" / "runtime-audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    record = {
        "schema": RUNTIME_AUDIT_SCHEMA,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "action": action,
        "plan_id": plan_id,
        "allowed_skills": allowed,
        "blocked_count": blocked_count,
    }
    path = audit_dir / f"{ts}-{target}-{action}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Auto-Load Hook: shell script installed per-target for startup staleness check
# ---------------------------------------------------------------------------


def _hook_path(target: str, home: Path | None = None) -> Path:
    """Return the path for the auto-load hook script.

    Lives at the top-level agent config dir, e.g. ``~/.hermes/agentmesh-auto-load.sh``.
    """
    if target not in RUNTIME_TARGETS:
        raise ValueError(f"暂不支持 runtime hook 目标：{target}")
    agent_dir = (home or Path.home()) / RUNTIME_TARGETS[target][0]
    return agent_dir / AUTO_LOAD_HOOK_NAME


def build_auto_load_hook_content(target: str, agentmesh_home: Path) -> str:
    """Generate the auto-load hook shell script content."""
    load_plan_path = agentmesh_home / "state" / "runtime-load-plans" / f"{target}.json"
    ts = datetime.now(timezone.utc).isoformat()
    return (
        "#!/usr/bin/env bash\n"
        f"# AgentMesh Auto-Load Hook — {target}\n"
        "# Auto-generated by AgentMesh bootstrap. Do not edit manually.\n"
        f"# Installed: {ts}\n"
        "\n"
        "set -euo pipefail\n"
        "\n"
        f"AGENTMESH_HOME='{agentmesh_home}'\n"
        f"AGENTMESH_TARGET='{target}'\n"
        f"AGENTMESH_LOAD_PLAN='{load_plan_path}'\n"
        "\n"
        "_check_and_update() {\n"
        '    local cmd=""\n'
        '    if command -v agentmesh &>/dev/null; then\n'
        '        cmd="agentmesh"\n'
        '    elif command -v python3 &>/dev/null; then\n'
        '        cmd="python3 -m agentmesh"\n'
        "    else\n"
        "        return 0\n"
        "    fi\n"
        "\n"
        "    local result\n"
        '    result=$($cmd runtime check-stale \\\n'
        '        --target "$AGENTMESH_TARGET" \\\n'
        '        --registry "$AGENTMESH_HOME" \\\n'
        "        --json 2>/dev/null) || return 0\n"
        "\n"
        "    local stale\n"
        '    stale=$(echo "$result" | python3 -c "\n'
        "import sys, json\n"
        "try:\n"
        "    d = json.load(sys.stdin)\n"
        "    print('true' if d.get('data', {}).get('stale', False) else 'false')\n"
        "except:\n"
        "    print('false')\n"
        '" 2>/dev/null) || return 0\n'
        "\n"
        '    if [ "$stale" = "true" ]; then\n'
        '        echo "[agentmesh-hook:$AGENTMESH_TARGET] LoadPlan stale, updating..." >&2\n'
        '        $cmd runtime update \\\n'
        '            --target "$AGENTMESH_TARGET" \\\n'
        '            --registry "$AGENTMESH_HOME" \\\n'
        "            --apply 2>/dev/null || true\n"
        "    fi\n"
        "}\n"
        "\n"
        "_check_and_update\n"
    )


def install_auto_load_hook(
    agentmesh_home: Path, target: str, home: Path | None = None
) -> Path:
    """Install the auto-load hook script for a target.

    Returns the path of the installed hook.
    """
    hook = _hook_path(target, home)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        build_auto_load_hook_content(target, agentmesh_home), encoding="utf-8"
    )
    hook.chmod(0o755)
    return hook


def uninstall_auto_load_hook(target: str, home: Path | None = None) -> bool:
    """Remove the auto-load hook script. Returns True if it existed."""
    hook = _hook_path(target, home)
    if hook.exists():
        hook.unlink()
        return True
    return False


def check_stale(agentmesh_home: Path, target: str) -> dict:
    """Lightweight staleness check for auto-load hook consumption.

    Returns a dict with keys: target, stale, skills_added, skills_removed,
    content_changed, error.
    """
    load_plan_path = agentmesh_home / "state" / "runtime-load-plans" / f"{target}.json"
    result = detect_load_plan_staleness(agentmesh_home, load_plan_path)
    return {
        "target": target,
        "stale": result["stale"],
        "skills_added": result["skills_added"],
        "skills_removed": result["skills_removed"],
        "content_changed": result["content_changed"],
        "error": result["error"],
    }
