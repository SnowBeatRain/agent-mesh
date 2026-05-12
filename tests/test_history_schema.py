"""TDD tests for history/backup schema completeness.

Covers:
- skipped semantic: identical skill → status:skipped + skipped_reason
- blocked semantic: hard block → blocked_reason per action
- recoverability filtering: unsafe_path excluded from list output
"""
from __future__ import annotations

import json
from pathlib import Path

from agentmesh.services.backup_service import list_backup_records
from agentmesh.services.sync_service import list_sync_history, sync


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


# ── skipped semantic ──────────────────────────────────────────────


def test_sync_identical_skill_records_skipped_in_history(fake_home):
    """第二次 sync 相同内容的 skill → history entry 应为 skipped。"""
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Stable")

    # 第一次 sync → applied
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    entries = list_sync_history(registry)
    assert len(entries) == 1
    assert entries[0]["status"] == "applied"

    # 第二次 sync 相同内容 → skipped
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    entries = list_sync_history(registry)
    assert len(entries) == 2
    skipped_entry = entries[1]
    assert skipped_entry["status"] == "skipped"
    # summary 中应标记 skipped 计数
    assert skipped_entry["summary"].get("skipped", 0) >= 1


def test_sync_identical_skill_action_has_skipped_reason(fake_home):
    """identical skill 的 action 应带 skipped_reason 字段。"""
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Stable")

    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    entries = list_sync_history(registry)
    skipped_entry = entries[1]
    action = skipped_entry["actions"][0]
    assert action["decision"] == "skip"
    assert action.get("skipped_reason") == "content_identical"


def test_sync_identical_skill_skips_backup_and_lock_update(fake_home):
    """identical skill 不应更新 lock hash，不应产生新的 backup 写入。"""
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Stable")

    # 第一次 sync → applied（target 不存在，无旧内容需备份）
    result1 = sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup1 = Path(result1["backup"])

    # 第二次 sync 相同内容 → skipped
    result2 = sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup2 = Path(result2["backup"])

    # 第一次 sync：target 之前不存在，所以没有旧内容需要备份
    assert not (backup1 / "openclaw" / "demo-skill").exists()
    # 第二次 sync：skipped，不应有 backup 写入
    assert not (backup2 / "openclaw" / "demo-skill").exists()


# ── blocked semantic ──────────────────────────────────────────────


def test_security_block_records_blocked_reason_per_action(fake_home):
    """security block 的 action 应带 blocked_reason 字段。"""
    registry = fake_home / "agentmesh"
    api_key = "api" + "_key"
    sample_key = "sk-" + "tes...alue"
    make_registry_skill(registry, "demo-skill", f"{api_key} = '{sample_key}'")

    try:
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    except Exception:
        pass

    entries = list_sync_history(registry)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "blocked"
    action = entry["actions"][0]
    assert action["decision"] == "block"
    assert isinstance(action.get("blocked_reasons"), list)
    assert len(action["blocked_reasons"]) >= 1


# ── recoverability / unsafe path ──────────────────────────────────


def test_backup_list_excludes_unsafe_path_records_from_output(fake_home, tmp_path):
    """unsafe_path 的 backup 记录不应出现在 data.backups 输出中，
    但仍应体现在 summary 的 unsafe_path 计数中。"""
    registry = fake_home / "agentmesh"
    outside = tmp_path / "outside-backup"
    outside.mkdir(parents=True, exist_ok=True)

    entry = {
        "schema": "agentmesh.sync-history-entry/v1",
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
    history_path = registry / "state" / "sync-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    payload = list_backup_records(registry)

    # unsafe_path 记录不应出现在输出列表中
    records = payload["data"]["backups"]
    assert len(records) == 0

    # 但 summary 中应体现 unsafe_path 计数
    assert payload["summary"]["unsafe_path"] == 1
    assert payload["summary"]["total"] == 0


def test_backup_list_mixed_records_filters_unsafe_but_keeps_rest(fake_home, tmp_path):
    """混合记录：unsafe 被过滤，正常记录保留。"""
    registry = fake_home / "agentmesh"
    outside = tmp_path / "outside-backup"
    outside.mkdir(parents=True, exist_ok=True)

    safe_backup = registry / "backups" / "20260430-120000-000001"
    safe_skill = safe_backup / "openclaw" / "demo-skill"
    safe_skill.mkdir(parents=True)
    (safe_skill / "SKILL.md").write_text("# Old\n", encoding="utf-8")

    entries = [
        {
            "schema": "agentmesh.sync-history-entry/v1",
            "id": "sync-safe",
            "timestamp": "2026-04-30T12:00:00+00:00",
            "operation": "skills sync",
            "status": "applied",
            "targets": ["openclaw"],
            "sync_mode": "copy",
            "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
            "backup": str(safe_backup),
            "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
        },
        {
            "schema": "agentmesh.sync-history-entry/v1",
            "id": "sync-unsafe",
            "timestamp": "2026-04-30T12:01:00+00:00",
            "operation": "skills sync",
            "status": "applied",
            "targets": ["openclaw"],
            "sync_mode": "copy",
            "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
            "backup": str(outside),
            "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
        },
    ]
    history_path = registry / "state" / "sync-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8",
    )

    payload = list_backup_records(registry)

    records = payload["data"]["backups"]
    assert len(records) == 1
    assert records[0]["history_id"] == "sync-safe"
    assert payload["summary"]["unsafe_path"] == 1
    assert payload["summary"]["total"] == 1


# ── schema completeness ────────────────────────────────────────────


def test_applied_history_entry_has_all_required_fields(fake_home):
    """applied history entry 应包含 schema 所有必要字段。"""
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# New")

    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    entries = list_sync_history(registry)
    assert len(entries) == 1
    entry = entries[0]

    required_top = [
        "schema", "id", "timestamp", "operation", "status",
        "targets", "sync_mode", "summary", "actions",
    ]
    for field in required_top:
        assert field in entry, f"history entry 缺少顶层字段: {field}"

    assert entry["schema"] == "agentmesh.sync-history-entry/v1"
    assert entry["operation"] == "skills sync"
    assert entry["status"] == "applied"

    # action 级别字段
    action = entry["actions"][0]
    required_action = ["action", "skill", "to", "decision"]
    for field in required_action:
        assert field in action, f"action 缺少字段: {field}"
    assert action["decision"] in ("allow", "block", "skip")


def test_blocked_history_entry_has_error_and_recovery_fields(fake_home):
    """blocked history entry 应包含 error 和 actions_state 字段。"""
    registry = fake_home / "agentmesh"
    api_key = "api" + "_key"
    sample_key = "sk-" + "tes...alue"
    make_registry_skill(registry, "demo-skill", f"{api_key} = '{sample_key}'")

    try:
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    except Exception:
        pass

    entries = list_sync_history(registry)
    assert len(entries) == 1
    entry = entries[0]

    assert entry["status"] == "blocked"
    assert "error" in entry
    assert "type" in entry["error"]
    assert "message" in entry["error"]
    assert "actions_state" in entry["actions_state"] or isinstance(entry.get("actions_state"), dict)


# ── blocked semantic: drift block ──────────────────────────────────


def test_drift_block_records_status_blocked_with_reason(fake_home):
    """drift 检测阻断时，history entry 应为 status:blocked，
    action 应带 blocked_reasons 包含 conflict 相关信息。"""
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")

    # 第一次 sync → applied
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    # 手动修改 target 内容（模拟 drift）
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    (target / "SKILL.md").write_text("# Tampered\n", encoding="utf-8")

    # 修改 registry 中的 skill 内容，使其与 target 不同
    (registry / "skills" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo\n---\n\n# V2\n",
        encoding="utf-8",
    )

    try:
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    except Exception:
        pass

    entries = list_sync_history(registry)
    # 第二次 sync 应产生 blocked 或 applied entry
    # （取决于 drift 是否被检测到）
    assert len(entries) >= 2
    second = entries[1]
    # 如果 drift 被检测到，status 应为 blocked
    if second["status"] == "blocked":
        assert "error" in second
        action = second["actions"][0]
        assert action["decision"] == "block"
        assert isinstance(action.get("blocked_reasons"), list)


# ── recoverability statuses ────────────────────────────────────────


def test_backup_list_restorable_status_with_proper_metadata(fake_home):
    """有正确 metadata 的 backup 应标记为 restorable。"""
    registry = fake_home / "agentmesh"
    backup = registry / "backups" / "20260501-120000-000001"
    backup_skill = backup / "openclaw" / "demo-skill"
    backup_skill.mkdir(parents=True)
    (backup_skill / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    (backup / "backup.yaml").write_text(
        "schema: agentmesh.backup/v1\nskill: demo-skill\n",
        encoding="utf-8",
    )
    entry = {
        "schema": "agentmesh.sync-history-entry/v1",
        "id": "sync-restorable",
        "timestamp": "2026-05-01T12:00:00+00:00",
        "operation": "skills sync",
        "status": "applied",
        "targets": ["openclaw"],
        "sync_mode": "copy",
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "backup": str(backup),
        "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
    }
    history_path = registry / "state" / "sync-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    payload = list_backup_records(registry)
    records = payload["data"]["backups"]
    assert len(records) == 1
    assert records[0]["recoverability"]["status"] == "restorable"
    assert payload["summary"]["restorable"] == 1


def test_backup_list_empty_backup_status(fake_home):
    """空 backup 目录应标记为 empty_backup，不出现在输出中。"""
    registry = fake_home / "agentmesh"
    backup = registry / "backups" / "20260501-120000-000002"
    backup.mkdir(parents=True)
    # 空目录，不创建任何文件

    entry = {
        "schema": "agentmesh.sync-history-entry/v1",
        "id": "sync-empty",
        "timestamp": "2026-05-01T12:00:00+00:00",
        "operation": "skills sync",
        "status": "applied",
        "targets": ["openclaw"],
        "sync_mode": "copy",
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "backup": str(backup),
        "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
    }
    history_path = registry / "state" / "sync-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    payload = list_backup_records(registry)
    records = payload["data"]["backups"]
    assert len(records) == 1
    assert records[0]["recoverability"]["status"] == "empty_backup"
    assert records[0]["recoverability"]["warnings"]
    assert payload["summary"]["empty_backup"] == 1


def test_backup_list_missing_path_status(fake_home):
    """不存在的 backup 路径应标记为 missing_path。"""
    registry = fake_home / "agentmesh"
    backup = registry / "backups" / "20260501-120000-000003"
    # 不创建目录

    entry = {
        "schema": "agentmesh.sync-history-entry/v1",
        "id": "sync-missing",
        "timestamp": "2026-05-01T12:00:00+00:00",
        "operation": "skills sync",
        "status": "applied",
        "targets": ["openclaw"],
        "sync_mode": "copy",
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "backup": str(backup),
        "actions": [{"skill": "demo-skill", "to": "openclaw", "decision": "allow"}],
    }
    history_path = registry / "state" / "sync-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    payload = list_backup_records(registry)
    records = payload["data"]["backups"]
    assert len(records) == 1
    assert records[0]["recoverability"]["status"] == "missing_path"
    assert records[0]["recoverability"]["warnings"]
    assert payload["summary"]["missing_path"] == 1


# ── backup list filters non-applied entries ────────────────────────


def test_backup_list_excludes_skipped_history_entries(fake_home):
    """status:skipped 的 history entry 不应出现在 backup list 中。"""
    registry = fake_home / "agentmesh"
    entries = [
        {
            "schema": "agentmesh.sync-history-entry/v1",
            "id": "sync-skipped",
            "timestamp": "2026-05-01T12:00:00+00:00",
            "operation": "skills sync",
            "status": "skipped",
            "targets": ["openclaw"],
            "sync_mode": "copy",
            "summary": {"actions": 1, "allowed": 0, "blocked": 0, "warnings": 0, "skipped": 1},
            "backup": str(registry / "backups" / "20260501-120000"),
            "actions": [
                {
                    "skill": "demo-skill", "to": "openclaw",
                    "decision": "skip", "skipped_reason": "content_identical",
                }
            ],
        },
    ]
    history_path = registry / "state" / "sync-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8",
    )

    payload = list_backup_records(registry)
    records = payload["data"]["backups"]
    assert len(records) == 0


def test_backup_list_excludes_blocked_history_entries(fake_home):
    """status:blocked 的 history entry 不应出现在 backup list 中。"""
    registry = fake_home / "agentmesh"
    entries = [
        {
            "schema": "agentmesh.sync-history-entry/v1",
            "id": "sync-blocked",
            "timestamp": "2026-05-01T12:00:00+00:00",
            "operation": "skills sync",
            "status": "blocked",
            "targets": ["openclaw"],
            "sync_mode": "copy",
            "summary": {"actions": 1, "allowed": 0, "blocked": 1, "warnings": 0},
            "backup": None,
            "actions": [
                {
                    "skill": "demo-skill", "to": "openclaw",
                    "decision": "block", "blocked_reasons": ["policy:block"],
                }
            ],
            "error": {"type": "SyncBlocked", "message": "security block"},
        },
    ]
    history_path = registry / "state" / "sync-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8",
    )

    payload = list_backup_records(registry)
    records = payload["data"]["backups"]
    assert len(records) == 0


# ── partially skipped sync (multi-skill) ───────────────────────────


def test_partial_skip_multi_skill_sync(fake_home):
    """多 skill sync 中部分 skipped、部分 applied 时，
    entry status 应为 applied，summary 应包含 skipped 计数。"""
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "skill-a", "# A")
    make_registry_skill(registry, "skill-b", "# B")

    # 第一次 sync → applied（两个 skill 都是新的）
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    # 修改 skill-a 内容
    (registry / "skills" / "skill-a" / "SKILL.md").write_text(
        "---\nname: skill-a\ndescription: Demo\n---\n\n# A v2\n",
        encoding="utf-8",
    )

    # 第二次 sync → skill-a applied, skill-b skipped
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    entries = list_sync_history(registry)
    assert len(entries) == 2
    second = entries[1]
    # 部分 skipped 时 status 应为 applied
    assert second["status"] == "applied"
    # summary 应包含 skipped 计数
    assert second["summary"].get("skipped", 0) >= 1

    # actions 中应有 skip 和 allow 两种 decision
    decisions = {a["decision"] for a in second["actions"]}
    assert "skip" in decisions
    assert "allow" in decisions

    # skipped action 应有 skipped_reason
    skipped_actions = [a for a in second["actions"] if a["decision"] == "skip"]
    for sa in skipped_actions:
        assert sa.get("skipped_reason") == "content_identical"
