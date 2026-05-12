from __future__ import annotations

import json
from pathlib import Path

from agentmesh.services.backup_service import list_backup_records
from agentmesh.services.rollback_service import build_rollback_plan
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


def make_registry_skill_backup(registry: Path) -> tuple[str, Path]:
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
                "target_path": str(
                    Path.home() / ".openclaw" / "workspace" / "skills" / "demo-skill"
                ),
                "decision": "allow",
            }
        ],
    }
    path = registry / "state" / "sync-history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    backup_id = list_backup_records(registry)["data"]["backups"][0]["backup_id"]
    return backup_id, backup


def test_build_rollback_plan_resolves_backup_id_for_missing_target(fake_home):
    registry = fake_home / "agentmesh"
    backup_id, backup = make_registry_skill_backup(registry)

    plan = build_rollback_plan(registry, backup_id, home=fake_home)

    assert plan["schema"] == "agentmesh.rollback-plan/v1"
    assert plan["command"] == "rollback plan"
    assert plan["status"] == "executable"
    assert plan["mode"] == "PLAN"
    assert plan["backup"]["backup_id"] == backup_id
    assert plan["backup"]["backup_path"] == str(backup)
    assert plan["backup"]["recoverability"] == "metadata_missing"
    assert plan["summary"]["actions"] == 1
    assert plan["summary"]["executable"] == 1
    action = plan["actions"][0]
    assert action["target"] == "openclaw"
    assert action["skill"] == "demo-skill"
    assert action["target_state"] == "metadata_missing"
    assert action["current_target_state"] == "missing"
    assert action["decision"] == "restore_tree"
    assert action["hard_block"] is False


def test_build_rollback_plan_resolves_history_id(fake_home):
    registry = fake_home / "agentmesh"
    _backup_id, _backup = make_registry_skill_backup(registry)

    plan = build_rollback_plan(registry, "sync-2026-04-30T12:00:00+00:00", home=fake_home)

    assert plan["status"] == "executable"
    assert plan["backup"]["history_id"] == "sync-2026-04-30T12:00:00+00:00"


def test_build_rollback_plan_resolves_backup_path(fake_home):
    registry = fake_home / "agentmesh"
    _backup_id, backup = make_registry_skill_backup(registry)

    plan = build_rollback_plan(registry, str(backup), home=fake_home)

    assert plan["status"] == "executable"
    assert plan["backup"]["backup_path"] == str(backup)


def test_build_rollback_plan_reports_ambiguous_history_id(fake_home):
    registry = fake_home / "agentmesh"
    _backup_id, _backup = make_registry_skill_backup(registry)
    history_file = registry / "state" / "sync-history.jsonl"
    original = history_file.read_text(encoding="utf-8")
    history_file.write_text(original + original, encoding="utf-8")

    plan = build_rollback_plan(registry, "sync-2026-04-30T12:00:00+00:00", home=fake_home)

    assert plan["status"] == "error"
    assert plan["errors"] == ["ambiguous_history"]


def test_build_rollback_plan_reports_non_eligible_history(fake_home):
    registry = fake_home / "agentmesh"
    path = registry / "state" / "sync-history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": "sync-no-backup",
                "timestamp": "2026-04-30T12:00:00+00:00",
                "operation": "skills sync",
                "status": "blocked",
                "targets": ["openclaw"],
                "sync_mode": "copy",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    plan = build_rollback_plan(registry, "sync-no-backup", home=fake_home)

    assert plan["status"] == "error"
    assert plan["errors"] == ["not_rollback_eligible"]


def test_build_rollback_plan_allows_managed_clean_target(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = list_backup_records(registry)["data"]["backups"][-1]["backup_id"]

    plan = build_rollback_plan(registry, backup_id, home=fake_home)

    assert plan["status"] == "executable"
    action = plan["actions"][0]
    assert action["current_target_state"] == "managed_clean"
    assert action["decision"] == "restore_tree"
    assert action["hard_block"] is False


def test_build_rollback_plan_blocks_managed_drift(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    (target / "SKILL.md").write_text("# User drift\n", encoding="utf-8")
    backup_id = list_backup_records(registry)["data"]["backups"][-1]["backup_id"]

    plan = build_rollback_plan(registry, backup_id, home=fake_home)

    assert plan["status"] == "blocked"
    action = plan["actions"][0]
    assert action["current_target_state"] == "managed_drift"
    assert action["decision"] == "block_drift"
    assert action["hard_block"] is True


def test_build_rollback_plan_blocks_unmanaged_target(fake_home):
    registry = fake_home / "agentmesh"
    backup_id, _backup = make_registry_skill_backup(registry)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# unmanaged\n", encoding="utf-8")

    plan = build_rollback_plan(registry, backup_id, home=fake_home)

    assert plan["status"] == "blocked"
    action = plan["actions"][0]
    assert action["current_target_state"] == "unmanaged"
    assert action["decision"] == "block_unmanaged"
    assert action["hard_block"] is True


def test_build_rollback_plan_blocks_missing_action_backup(fake_home):
    registry = fake_home / "agentmesh"
    backup_id, backup = make_registry_skill_backup(registry)
    backup_skill = backup / "openclaw" / "demo-skill"
    for child in backup_skill.iterdir():
        child.unlink()
    backup_skill.rmdir()

    plan = build_rollback_plan(registry, backup_id, home=fake_home)

    assert plan["status"] == "blocked"
    action = plan["actions"][0]
    assert action["decision"] in {"block_backup_missing", "block_partial"}
    assert action["hard_block"] is True


def test_build_rollback_plan_blocks_target_path_guard_violation_as_unsafe(fake_home, monkeypatch):
    registry = fake_home / "agentmesh"
    backup_id, _backup = make_registry_skill_backup(registry)

    import agentmesh.services.rollback_service as rollback_service

    def unsafe_target_skill_path(name: str, target: str, home: Path | None = None) -> Path:
        base = home or fake_home
        return base / ".codex" / "skills" / ".system" / name

    monkeypatch.setattr(rollback_service, "target_skill_path", unsafe_target_skill_path)

    plan = build_rollback_plan(registry, backup_id, home=fake_home)

    assert plan["status"] == "blocked"
    action = plan["actions"][0]
    assert action["current_target_state"] == "unsafe_path"
    assert action["target_state"] == "unsafe_path"
    assert action["decision"] == "block_unsafe_path"
    assert action["hard_block"] is True


def test_build_rollback_plan_blocks_unsafe_path_without_inspecting(
    fake_home, tmp_path, monkeypatch
):
    registry = fake_home / "agentmesh"
    outside = tmp_path / "outside-backup"
    path = registry / "state" / "sync-history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": "sync-unsafe",
                "timestamp": "2026-04-30T12:00:00+00:00",
                "operation": "skills sync",
                "status": "applied",
                "targets": ["openclaw"],
                "sync_mode": "copy",
                "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
                "backup": str(outside),
                "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    original_exists = Path.exists

    def fail_exists(self):
        if self == outside.resolve():
            raise AssertionError("unsafe backup path must not be inspected")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fail_exists)

    plan = build_rollback_plan(registry, str(outside), home=fake_home)

    assert plan["status"] == "blocked"
    assert plan["backup"]["recoverability"] == "unsafe_path"
    assert plan["summary"]["hard_blocks"] == 1


def test_build_rollback_plan_treats_managed_symlink_as_separate_restore_semantics(fake_home):
    registry = fake_home / "agentmesh"
    backup_id, backup = make_registry_skill_backup(registry)
    history_file = registry / "state" / "sync-history.jsonl"
    entry = json.loads(history_file.read_text(encoding="utf-8"))
    entry["sync_mode"] = "symlink"
    history_file.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    make_registry_skill(registry, "demo-skill", "# linked registry source")
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(registry / "skills" / "demo-skill", target_is_directory=True)
    link_lock = target.parent / ".demo-skill.agentmesh-link.yaml"
    link_lock.write_text(
        "schema: agentmesh.link-lock/v1\nskill: demo-skill\ntarget: openclaw\nmode: symlink\n",
        encoding="utf-8",
    )

    plan = build_rollback_plan(registry, backup_id, home=fake_home)

    assert plan["status"] == "executable"
    assert plan["backup"]["backup_path"] == str(backup)
    action = plan["actions"][0]
    assert action["current_target_state"] == "managed_symlink"
    assert action["decision"] == "restore_managed_symlink_to_tree"
    assert action["hard_block"] is False


def test_build_rollback_plan_rebuilds_current_state_every_time(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = list_backup_records(registry)["data"]["backups"][-1]["backup_id"]

    initial = build_rollback_plan(registry, backup_id, home=fake_home)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    (target / "SKILL.md").write_text("# drift after old plan\n", encoding="utf-8")
    rebuilt = build_rollback_plan(registry, backup_id, home=fake_home)

    assert initial["status"] == "executable"
    assert initial["actions"][0]["current_target_state"] == "managed_clean"
    assert rebuilt["status"] == "blocked"
    assert rebuilt["actions"][0]["current_target_state"] == "managed_drift"
    assert rebuilt["actions"][0]["decision"] == "block_drift"
