from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmesh.services.sync_service import SyncBlocked, list_sync_history, sync


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


def test_apply_creates_timestamped_backup_and_lock(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# New")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Old\n", encoding="utf-8")

    result = sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    assert result["mode"] == "APPLY"
    backup_root = Path(result["backup"])
    assert backup_root.name != "latest"
    assert (backup_root / "openclaw" / "demo-skill" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# Old\n"
    assert "# New" in (target / "SKILL.md").read_text(encoding="utf-8")

    lock = target / ".agentmesh-lock.yaml"
    assert lock.exists()
    lock_text = lock.read_text(encoding="utf-8")
    assert "skill: demo-skill" in lock_text
    assert "target: openclaw" in lock_text


def test_apply_blocks_drift_without_overwriting(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Desired")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# AgentMesh managed v1\n", encoding="utf-8")
    (target / ".agentmesh-lock.yaml").write_text(
        "schema: agentmesh.lock/v1\nskill: demo-skill\ntarget: openclaw\nhash: stale-hash\n",
        encoding="utf-8",
    )

    with pytest.raises(SyncBlocked, match="drift"):
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "# AgentMesh managed v1\n"


def test_apply_blocks_security_findings_without_writing(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "api_key = 'registry-secret'")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Safe old\n", encoding="utf-8")

    with pytest.raises(SyncBlocked, match="security"):
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "# Safe old\n"
    assert "registry-secret" not in str(registry / "logs")


def test_apply_rolls_back_when_copy_fails(fake_home, monkeypatch):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# New")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Old\n", encoding="utf-8")

    import agentmesh.services.sync_service as sync_service

    original_copytree = sync_service.copytree

    def failing_copytree(src, dst, *args, **kwargs):
        if Path(src).name == "demo-skill" and Path(dst) == target:
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text("# Partial\n", encoding="utf-8")
            raise OSError("simulated copy failure")
        return original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(sync_service, "copytree", failing_copytree)

    with pytest.raises(OSError, match="simulated copy failure"):
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "# Old\n"


def test_apply_failure_records_failed_history_with_action_state(fake_home, monkeypatch):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# New")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Old\n", encoding="utf-8")

    import agentmesh.services.sync_service as sync_service

    original_copytree = sync_service.copytree

    def failing_copytree(src, dst, *args, **kwargs):
        if Path(src).name == "demo-skill" and Path(dst) == target:
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text("# Partial\n", encoding="utf-8")
            raise OSError("simulated copy failure")
        return original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(sync_service, "copytree", failing_copytree)

    with pytest.raises(OSError, match="simulated copy failure"):
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    entries = list_sync_history(registry)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "failed"
    assert entry["error"]["type"] == "OSError"
    assert entry["recovery"]["attempted"] is True
    assert entry["recovery"]["guarantee"] == "best_effort"
    assert entry["actions_state"]["attempted"] == ["openclaw:demo-skill"]
    assert entry["actions_state"]["failed"] == ["openclaw:demo-skill"]
    assert entry["actions_state"]["applied"] == []


def test_apply_records_sync_history_jsonl(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# New")

    result = sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    result_actions = json.loads(json.dumps(result["actions"], ensure_ascii=False))

    history_file = registry / "state" / "sync-history.jsonl"
    assert history_file.exists()
    entries = list_sync_history(registry)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["schema"] == "agentmesh.sync-history-entry/v1"
    assert entry["operation"] == "skills sync"
    assert entry["status"] == "applied"
    assert entry["sync_mode"] == "copy"
    assert entry["targets"] == ["openclaw"]
    assert entry["summary"] == result["summary"]
    assert entry["backup"] == result["backup"]
    assert entry["actions"] == result_actions
    assert "timestamp" in entry
    assert "id" in entry


def test_sync_dry_run_does_not_record_history(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# New")

    result = sync(registry, ["openclaw"], apply=False)

    assert result["mode"] == "DRY-RUN"
    assert list_sync_history(registry) == []
    assert not (registry / "state" / "sync-history.jsonl").exists()


def test_security_block_records_blocked_history_without_secret(fake_home):
    registry = fake_home / "agentmesh"
    sample_key = "sk-" + "tes...alue"
    key_name = "api" + "_key"
    make_registry_skill(registry, "demo-skill", f"{key_name} = '{sample_key}'")

    with pytest.raises(SyncBlocked, match="security"):
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    entries = list_sync_history(registry)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "blocked"
    assert entry["error"]["type"] == "SyncBlocked"
    assert "security" in entry["error"]["message"]
    assert entry["summary"]["blocked"] >= 1
    assert sample_key not in json.dumps(entry, ensure_ascii=False)


def test_symlink_apply_creates_directory_link_and_sidecar_lock(fake_home):
    registry = fake_home / "agentmesh"
    source = make_registry_skill(registry, "demo-skill", "# Registry")

    try:
        result = sync(registry, ["openclaw"], apply=True, mode="symlink", confirm=True)
    except SyncBlocked as exc:
        if "symlink failed" in str(exc):
            pytest.skip(str(exc))
        raise

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    lock = target.parent / ".demo-skill.agentmesh-link.yaml"
    assert result["sync_mode"] == "symlink"
    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert lock.exists()
    assert "mode: symlink" in lock.read_text(encoding="utf-8")
    assert not (source / ".agentmesh-lock.yaml").exists()


def test_symlink_apply_blocks_unmanaged_existing_symlink(fake_home, tmp_path):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Registry")
    external = tmp_path / "external-skill"
    external.mkdir()
    (external / "SKILL.md").write_text("# External\n", encoding="utf-8")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(str(exc))

    with pytest.raises(SyncBlocked, match="not managed"):
        sync(registry, ["openclaw"], apply=True, mode="symlink", confirm=True)

    assert target.resolve() == external.resolve()


def test_symlink_apply_blocks_content_conflict_without_overwriting(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Registry")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo\n---\n\n# Target\n",
        encoding="utf-8",
    )

    with pytest.raises(SyncBlocked, match="conflict"):
        sync(registry, ["openclaw"], apply=True, mode="symlink", confirm=True)

    assert not target.is_symlink()
    assert "# Target" in (target / "SKILL.md").read_text(encoding="utf-8")


def test_symlink_apply_blocks_file_target(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Registry")

    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.parent.mkdir(parents=True)
    target.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(SyncBlocked, match="not a skill directory"):
        sync(registry, ["openclaw"], apply=True, mode="symlink", confirm=True)

    assert target.read_text(encoding="utf-8") == "not a directory\n"
