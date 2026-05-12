from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.backup_service import list_backup_records
from agentmesh.services.sync_service import sync


def make_registry_skill(registry: Path, name: str, body: str = "# Registry") -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    return skill


def test_backup_list_json_returns_backup_records(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    result = CliRunner().invoke(app, ["backup", "list", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.backup-list/v1"
    assert payload["command"] == "backup list"
    assert payload["status"] == "ok"
    backups = payload["data"]["backups"]
    assert len(backups) == 1
    assert backups[0]["backup_id"].startswith("bkp-")
    assert backups[0]["history_id"].startswith("sync-")


def test_rollback_plan_json_returns_read_only_plan(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = list_backup_records(registry)["data"]["backups"][-1]["backup_id"]

    result = CliRunner().invoke(
        app, ["rollback", "plan", backup_id, "--registry", str(registry), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.rollback-plan-response/v1"
    assert payload["command"] == "rollback plan"
    assert payload["status"] == "executable"
    assert isinstance(payload["warnings"], list)
    assert payload["errors"] == []
    assert "data" in payload
    plan = payload["data"]["plan"]
    assert plan["schema"] == "agentmesh.rollback-plan/v1"
    assert plan["mode"] == "PLAN"
    assert plan["backup"]["backup_id"] == backup_id
    assert plan["actions"][0]["decision"] == "restore_tree"


def test_rollback_apply_json_applies_rollback(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = list_backup_records(registry)["data"]["backups"][-1]["backup_id"]

    result = CliRunner().invoke(
        app, ["rollback", "apply", backup_id, "--registry", str(registry), "--confirm", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.rollback-apply/v1"
    assert payload["command"] == "rollback apply"
    assert payload["mode"] == "APPLY"
    assert payload["status"] == "applied"
    assert payload["summary"]["applied"] == 1
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    assert "# V1" in (target / "SKILL.md").read_text(encoding="utf-8")
