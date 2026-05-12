from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.utils.yaml_io import read_yaml


def make_skill(registry: Path, name: str = "demo-skill", body: str = "# Demo\n") -> None:
    skill = registry / "registry" / "assets" / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )


def test_runtime_load_plan_reports_registry_and_allowed_skills(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    runner = CliRunner()

    result = runner.invoke(
        app, ["runtime", "load-plan", "--registry", str(registry), "--target", "hermes", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.runtime-load-plan-response/v1"
    assert data["command"] == "runtime load-plan"
    assert data["status"] == "ok"
    assert data["warnings"] == []
    assert data["errors"] == []
    plan = data["data"]["plan"]
    assert plan["schema"] == "agentmesh.runtime-load-plan/v1"
    assert plan["plan_id"].startswith("rtlp-")
    assert plan["generated_at"]
    assert plan["load_plan_path"] == str(registry / "state" / "runtime-load-plans" / "hermes.json")
    assert plan["target"] == "hermes"
    assert plan["registry"] == str(registry / "registry")
    assert plan["mode"] == "direct-registry-read"
    assert plan["summary"] == {"skills": 1, "allowed": 1, "blocked": 0}
    assert plan["skills"] == [{"name": "demo-skill", "decision": "allow", "blocked_reasons": []}]
    persisted = registry / "state" / "runtime-load-plans" / "hermes.json"
    assert json.loads(persisted.read_text(encoding="utf-8")) == plan


def test_runtime_env_outputs_shell_exports(tmp_path):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    runner = CliRunner()

    result = runner.invoke(
        app, ["runtime", "env", "--registry", str(registry), "--target", "openclaw"]
    )

    assert result.exit_code == 0, result.output
    assert f"AGENTMESH_HOME='{registry}'" in result.output
    assert f"AGENTMESH_REGISTRY='{registry / 'registry'}'" in result.output
    assert "AGENTMESH_TARGET='openclaw'" in result.output


def test_runtime_validate_delegates_to_skills_validate_native(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("PATH", "")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["runtime", "validate", "--registry", str(registry), "--target", "hermes", "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["target"] == "hermes"
    assert data["native_validation"]["status"] == "skipped"
    assert data["ok"] is True


def test_runtime_bootstrap_dry_run_does_not_write_loader(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["runtime", "bootstrap", "--registry", str(registry), "--target", "openclaw", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Bootstrap plan for openclaw" in result.output
    assert "No files were changed" in result.output
    assert "Run with --apply to enable" in result.output
    assert not (tmp_path / ".openclaw" / "workspace" / "skills" / "agentmesh-loader").exists()


def test_runtime_bootstrap_json_contract_includes_schema_status_and_next_steps(
    tmp_path, monkeypatch
):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "openclaw",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.runtime-bootstrap/v1"
    assert data["command"] == "runtime bootstrap"
    assert data["status"] == "planned"
    assert data["dry_run"] is True
    assert data["warnings"] == []
    assert data["errors"] == []
    assert data["next_steps"] == ["Run with --apply to enable the bootstrap shim."]
    assert data["data"]["target"] == "openclaw"
    assert data["data"]["summary"] == {"skills": 1, "allowed": 1, "blocked": 0}


def test_runtime_bootstrap_blocks_unmanaged_existing_loader(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("HOME", str(tmp_path))
    loader = tmp_path / ".openclaw" / "workspace" / "skills" / "agentmesh-loader"
    loader.mkdir(parents=True)
    (loader / "SKILL.md").write_text("# user loader\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "openclaw",
            "--apply",
            "--json",
        ],
    )

    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["status"] == "blocked"
    assert data["errors"] == ["target loader path exists but is not managed by AgentMesh"]
    assert data["next_steps"] == [
        "Move or review the existing loader directory, then rerun with --dry-run."
    ]
    assert (loader / "SKILL.md").read_text(encoding="utf-8") == "# user loader\n"


def test_runtime_bootstrap_apply_and_status_disable_loader(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    applied = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "openclaw",
            "--apply",
            "--json",
        ],
    )
    assert applied.exit_code == 0, applied.output
    applied_data = json.loads(applied.output)
    assert applied_data["status"] == "applied"
    assert applied_data["dry_run"] is False
    assert applied_data["next_steps"] == [
        "Run `agentmesh runtime status --target openclaw` to inspect it."
    ]
    loader = tmp_path / ".openclaw" / "workspace" / "skills" / "agentmesh-loader"
    assert (loader / "SKILL.md").exists()
    assert "AGENTMESH_REGISTRY" in (loader / "agentmesh.env").read_text(encoding="utf-8")

    status = runner.invoke(
        app, ["runtime", "status", "--registry", str(registry), "--target", "openclaw", "--json"]
    )
    assert status.exit_code == 0, status.output
    status_data = json.loads(status.output)
    assert status_data["schema"] == "agentmesh.runtime-status/v1"
    assert status_data["status"] == "installed"
    assert status_data["data"]["installed"] is True
    assert status_data["data"]["managed"] is True

    disabled = runner.invoke(
        app,
        [
            "runtime",
            "disable",
            "--registry",
            str(registry),
            "--target",
            "openclaw",
            "--apply",
            "--json",
        ],
    )
    assert disabled.exit_code == 0, disabled.output
    disabled_data = json.loads(disabled.output)
    assert disabled_data["schema"] == "agentmesh.runtime-disable/v1"
    assert disabled_data["status"] == "disabled"
    assert disabled_data["data"]["backup"]
    assert not loader.exists()


def test_runtime_loader_entrypoint_points_to_persisted_load_plan(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    make_skill(registry)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    applied = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "openclaw",
            "--apply",
            "--json",
        ],
    )
    assert applied.exit_code == 0, applied.output

    loader = tmp_path / ".openclaw" / "workspace" / "skills" / "agentmesh-loader"
    load_plan_path = registry / "state" / "runtime-load-plans" / "openclaw.json"
    entrypoint = loader / "agentmesh_loader.py"
    assert entrypoint.exists()
    assert load_plan_path.exists()

    load_plan = json.loads(load_plan_path.read_text(encoding="utf-8"))
    assert load_plan["schema"] == "agentmesh.runtime-load-plan/v1"

    manifest = read_yaml(loader / "agentmesh-loader.yaml")
    assert manifest["entrypoint"] == "agentmesh_loader.py"
    assert manifest["load_plan_path"] == str(load_plan_path)
    assert manifest["load_plan_schema"] == "agentmesh.runtime-load-plan/v1"

    env = (loader / "agentmesh.env").read_text(encoding="utf-8")
    assert f"AGENTMESH_LOAD_PLAN='{load_plan_path}'" in env
    assert f"AGENTMESH_LOADER_ENTRYPOINT='{entrypoint}'" in env

    entrypoint_text = entrypoint.read_text(encoding="utf-8")
    assert "AGENTMESH_LOAD_PLAN" in entrypoint_text
    assert "agentmesh.runtime-load-plan/v1" in entrypoint_text

    executed = runner.invoke(
        app, ["runtime", "exec-plan", "--load-plan", str(load_plan_path), "--json"]
    )
    assert executed.exit_code == 0, executed.output
    executed_data = json.loads(executed.output)
    assert executed_data["schema"] == "agentmesh.runtime-exec-plan/v1"
    assert executed_data["status"] == "planned"
    assert executed_data["data"]["target"] == "openclaw"
    assert executed_data["data"]["summary"] == {"allowed": 1, "blocked": 0, "skills": 1}
    assert executed_data["data"]["actions"] == [
        {"action": "load-skill", "name": "demo-skill", "decision": "allow"}
    ]

    env_vars = {**os.environ, "AGENTMESH_LOAD_PLAN": str(load_plan_path)}
    entrypoint_result = subprocess.run(
        [sys.executable, str(entrypoint)],
        check=True,
        capture_output=True,
        text=True,
        env=env_vars,
        timeout=30,
    )
    entrypoint_data = json.loads(entrypoint_result.stdout)
    assert entrypoint_data == {
        "schema": "agentmesh.runtime-load-plan/v1",
        "actions": [{"action": "load-skill", "name": "demo-skill", "decision": "allow"}],
    }


def test_runtime_exec_plan_blocks_policy_blocked_skills(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    make_skill(registry, name="secret-skill", body="API_KEY='sk-test-secret'\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    applied = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "openclaw",
            "--apply",
            "--json",
        ],
    )
    assert applied.exit_code == 0, applied.output

    load_plan_path = registry / "state" / "runtime-load-plans" / "openclaw.json"
    executed = runner.invoke(
        app, ["runtime", "exec-plan", "--load-plan", str(load_plan_path), "--json"]
    )

    assert executed.exit_code == 0, executed.output
    data = json.loads(executed.output)
    assert data["data"]["summary"] == {"allowed": 0, "blocked": 1, "skills": 1}
    assert data["data"]["actions"] == [
        {"action": "block-skill", "name": "secret-skill", "decision": "block"}
    ]


def test_runtime_generated_loader_rejects_missing_schema(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    runner = CliRunner()
    runner.invoke(app, ["init", "--registry", str(registry)])
    make_skill(registry, name="demo-skill")

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "openclaw",
            "--apply",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    load_plan_path = registry / "state/runtime-load-plans/openclaw.json"
    load_plan = json.loads(load_plan_path.read_text(encoding="utf-8"))
    load_plan.pop("schema")
    load_plan_path.write_text(json.dumps(load_plan), encoding="utf-8")

    entrypoint = home / ".openclaw/workspace/skills/agentmesh-loader/agentmesh_loader.py"
    env = os.environ.copy()
    env["AGENTMESH_LOAD_PLAN"] = str(load_plan_path)
    completed = subprocess.run(
        [sys.executable, str(entrypoint)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode != 0
    assert "unsupported load plan schema: None" in completed.stderr


def test_runtime_exec_plan_reports_missing_load_plan_file(tmp_path):
    runner = CliRunner()
    missing = tmp_path / "missing.json"
    result = runner.invoke(
        app,
        ["runtime", "exec-plan", "--load-plan", str(missing), "--json"],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.runtime-exec-plan/v1"
    assert data["status"] == "error"
    assert data["data"] == {"load_plan": str(missing)}
    assert data["errors"]
    assert str(missing) in data["errors"][0]


def test_runtime_exec_plan_reports_invalid_json(tmp_path):
    runner = CliRunner()
    load_plan_path = tmp_path / "load-plan.json"
    load_plan_path.write_text("{not-json", encoding="utf-8")

    result = runner.invoke(
        app,
        ["runtime", "exec-plan", "--load-plan", str(load_plan_path), "--json"],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.runtime-exec-plan/v1"
    assert data["status"] == "error"
    assert data["data"] == {"load_plan": str(load_plan_path)}
    assert data["errors"]
    assert "Expecting property name" in data["errors"][0]


def test_runtime_exec_plan_rejects_invalid_load_plan_schema(tmp_path):
    load_plan_path = tmp_path / "bad-load-plan.json"
    load_plan_path.write_text(
        json.dumps({"schema": "agentmesh.runtime-load-plan/v0", "skills": []}),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app, ["runtime", "exec-plan", "--load-plan", str(load_plan_path), "--json"]
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.runtime-exec-plan/v1"
    assert data["status"] == "error"
    assert data["errors"] == ["unsupported load plan schema: agentmesh.runtime-load-plan/v0"]


# --- Renderer Integration Tests ---


def test_bootstrap_renders_skill_content_into_hermes_loader(tmp_path, monkeypatch):
    """E2E: apply_bootstrap for hermes renders allowed skill SKILL.md body into loader SKILL.md."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "hello-skill", "Say hello politely.\n")
    make_skill(registry, "review-skill", "Review code for quality.\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--apply",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "applied"
    assert data["data"]["rendered_skills"] == 2

    loader = tmp_path / ".hermes" / "skills" / "custom" / "agentmesh-loader"
    skill_md = (loader / "SKILL.md").read_text(encoding="utf-8")
    assert "AgentMesh Auto-Loaded Skills" in skill_md
    assert "## hello-skill" in skill_md
    assert "Say hello politely" in skill_md
    assert "## review-skill" in skill_md
    assert "Review code for quality" in skill_md
    assert "agentmesh runtime disable" in skill_md


def test_bootstrap_renders_mdc_for_cursor(tmp_path, monkeypatch):
    """E2E: apply_bootstrap for cursor renders .mdc rule file."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "python-rules", "Use type hints.\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "cursor",
            "--apply",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output

    rules_dir = tmp_path / ".cursor" / "rules"
    mdc = (rules_dir / "agentmesh-rules.mdc").read_text(encoding="utf-8")
    assert "---" in mdc
    assert "alwaysApply: true" in mdc
    assert "## python-rules" in mdc
    assert "Use type hints" in mdc


def test_bootstrap_renders_md_for_windsurf(tmp_path, monkeypatch):
    """E2E: apply_bootstrap for windsurf renders .md rules file."""
    registry = tmp_path / "agentmesh"
    make_skill(registry, "ts-rules", "Use strict mode.\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "windsurf",
            "--apply",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output

    rules_dir = tmp_path / ".windsurf" / "rules"
    md = (rules_dir / "agentmesh-rules.md").read_text(encoding="utf-8")
    assert "## ts-rules" in md
    assert "Use strict mode" in md


def test_bootstrap_blocked_skill_excluded_from_render(tmp_path, monkeypatch):
    """E2E: blocked skills (policy:block) are not rendered into loader content."""
    registry = tmp_path / "agentmesh"
    # Create a skill with a secret — will be blocked by audit
    secret_skill = registry / "registry" / "assets" / "skills" / "secret-skill"
    secret_skill.mkdir(parents=True, exist_ok=True)
    (secret_skill / "SKILL.md").write_text(
        "---\nname: secret-skill\ndescription: Has secret\n---\n\nAPI_KEY=sk-12345\n",
        encoding="utf-8",
    )
    (secret_skill / "agentmesh.asset.yaml").write_text(
        "schema: agentmesh.asset/v1\nkind: skill\nname: secret-skill\n",
        encoding="utf-8",
    )
    make_skill(registry, "safe-skill", "This is safe.\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "runtime",
            "bootstrap",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--apply",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    # secret-skill should be blocked, safe-skill allowed
    assert data["data"]["rendered_skills"] == 1

    loader = tmp_path / ".hermes" / "skills" / "custom" / "agentmesh-loader"
    skill_md = (loader / "SKILL.md").read_text(encoding="utf-8")
    assert "## safe-skill" in skill_md
    assert "secret-skill" not in skill_md
    assert "sk-12345" not in skill_md

    # Verify audit record written
    audit_dir = registry / "state" / "runtime-audit"
    assert audit_dir.is_dir()
    audit_files = list(audit_dir.glob("*.json"))
    assert len(audit_files) >= 1
    rec = json.loads(audit_files[-1].read_text(encoding="utf-8"))
    assert rec["schema"] == "agentmesh.runtime-audit/v1"
    assert rec["target"] == "hermes"
    assert rec["action"] == "bootstrap"
    assert rec["plan_id"] is not None
    assert "safe-skill" in rec["allowed_skills"]
    assert rec["blocked_count"] >= 1


def test_disable_bootstrap_writes_audit(tmp_path, monkeypatch):
    """disable_bootstrap creates an audit record."""
    from agentmesh.services.runtime_service import apply_bootstrap, disable_bootstrap

    registry = tmp_path / "agentmesh"
    make_skill(registry, "audit-skill", "Audit content.\n")
    monkeypatch.setenv("HOME", str(tmp_path))

    # Bootstrap first
    apply_bootstrap(registry, "hermes")
    audit_dir = registry / "state" / "runtime-audit"
    bootstrap_audits = list(audit_dir.glob("*-bootstrap.json"))
    assert len(bootstrap_audits) == 1

    # Now disable (apply=True to actually remove loader + write audit)
    disable_bootstrap(registry, "hermes", apply=True)
    disable_audits = list(audit_dir.glob("*-disable.json"))
    assert len(disable_audits) == 1
    rec = json.loads(disable_audits[0].read_text(encoding="utf-8"))
    assert rec["action"] == "disable"
    assert rec["target"] == "hermes"
    assert rec["allowed_skills"] == []
    assert rec["blocked_count"] == 0
