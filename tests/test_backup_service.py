from __future__ import annotations

import json
from pathlib import Path

from agentmesh.services.backup_service import list_backup_records


def write_history_entry(registry: Path, entry: dict) -> None:
    path = registry / "state" / "sync-history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")


def test_list_backup_records_projects_history_to_metadata_missing_record(tmp_path):
    registry = tmp_path / "agentmesh"
    backup = registry / "backups" / "20260430-120000-000001"
    backup_skill = backup / "openclaw" / "demo-skill"
    backup_skill.mkdir(parents=True)
    (backup_skill / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    entry = {
        "schema": "agentmesh.sync-history-entry/v1",
        "id": "sync-2026-04-30T12:00:00+00:00",
        "timestamp": "2026-04-30T12:00:00+00:00",
        "operation": "skills sync",
        "status": "applied",
        "targets": ["openclaw"],
        "sync_mode": "copy",
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "backup": str(backup),
        "actions": [
            {
                "skill": "demo-skill",
                "to": "openclaw",
                "target_path": "/tmp/fake-home/.openclaw/workspace/skills/demo-skill",
                "decision": "allow",
            }
        ],
    }
    write_history_entry(registry, entry)

    payload = list_backup_records(registry)

    assert payload["schema"] == "agentmesh.backup-list/v1"
    records = payload["data"]["backups"]
    assert len(records) == 1
    record = records[0]
    assert record["backup_id"].startswith("bkp-")
    assert len(record["backup_id"]) == len("bkp-") + 12
    assert record["history_id"] == entry["id"]
    assert record["backup_path"] == str(backup)
    assert record["sync_mode"] == "copy"
    assert record["action_refs"] == [
        {
            "target": "openclaw",
            "skill": "demo-skill",
            "target_path": "/tmp/fake-home/.openclaw/workspace/skills/demo-skill",
            "decision": "allow",
        }
    ]
    assert record["recoverability"]["status"] == "metadata_missing"
    assert record["metadata"] == {
        "present": False,
        "schema": None,
        "path": None,
        "readable": False,
        "supported": False,
    }


def test_list_backup_records_marks_unsafe_path_without_reading(tmp_path, monkeypatch):
    registry = tmp_path / "agentmesh"
    outside = tmp_path / "outside-backup"
    entry = {
        "id": "sync-unsafe",
        "timestamp": "2026-04-30T12:00:00+00:00",
        "operation": "skills sync",
        "status": "applied",
        "targets": ["openclaw"],
        "sync_mode": "copy",
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "backup": str(outside),
        "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
    }
    write_history_entry(registry, entry)

    original_exists = Path.exists

    def fail_exists(self):
        if self == outside.resolve():
            raise AssertionError("unsafe backup path must not be inspected")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fail_exists)

    payload = list_backup_records(registry)

    # unsafe_path 记录不应出现在输出列表中
    assert len(payload["data"]["backups"]) == 0
    # 但应体现在 summary 的 unsafe_path 计数中
    assert payload["summary"]["unsafe_path"] == 1


def test_list_backup_records_marks_unparseable_metadata_as_partial(tmp_path):
    registry = tmp_path / "agentmesh"
    backup = registry / "backups" / "20260430-120000-000002"
    backup_skill = backup / "openclaw" / "demo-skill"
    backup_skill.mkdir(parents=True)
    (backup_skill / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    (backup / "backup.yaml").write_text("schema: [broken\n", encoding="utf-8")
    entry = {
        "id": "sync-bad-metadata",
        "timestamp": "2026-04-30T12:00:00+00:00",
        "operation": "skills sync",
        "status": "applied",
        "targets": ["openclaw"],
        "sync_mode": "copy",
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "backup": str(backup),
        "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
    }
    write_history_entry(registry, entry)

    payload = list_backup_records(registry)

    record = payload["data"]["backups"][0]
    assert record["metadata"]["present"] is True
    assert record["metadata"]["schema"] is None
    assert record["metadata"]["readable"] is False
    assert record["metadata"]["supported"] is False
    assert record["recoverability"]["status"] == "partial"
