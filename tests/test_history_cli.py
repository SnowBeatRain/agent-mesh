from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
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


def test_history_list_json_returns_sync_history(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# New")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    result = CliRunner().invoke(app, ["history", "list", "--registry", str(registry), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.history-list/v1"
    assert payload["command"] == "history list"
    assert payload["status"] == "ok"
    entries = payload["data"]["entries"]
    assert len(entries) == 1
    assert entries[0]["schema"] == "agentmesh.sync-history-entry/v1"
    assert entries[0]["operation"] == "skills sync"
    assert entries[0]["status"] == "applied"
    assert entries[0]["targets"] == ["openclaw"]
