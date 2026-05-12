from __future__ import annotations

from pathlib import Path

import pytest

from agentmesh.services.backup_service import list_backup_records
from agentmesh.services.rollback_service import RollbackApplyBlocked, apply_rollback
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


def latest_backup_id(registry: Path) -> str:
    return list_backup_records(registry)["data"]["backups"][-1]["backup_id"]


def test_apply_rollback_requires_confirm(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    with pytest.raises(RollbackApplyBlocked, match="confirm_required"):
        apply_rollback(registry, latest_backup_id(registry), confirm=False, home=fake_home)


def test_apply_rollback_restores_backup_tree_and_writes_history(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = latest_backup_id(registry)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    assert "# V2" in (target / "SKILL.md").read_text(encoding="utf-8")

    result = apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert result["schema"] == "agentmesh.rollback-apply/v1"
    assert result["command"] == "rollback apply"
    assert result["status"] == "applied"
    assert result["summary"]["applied"] == 1
    assert "# V1" in (target / "SKILL.md").read_text(encoding="utf-8")
    rollback_history = registry / "state" / "rollback-history.jsonl"
    assert rollback_history.exists()
    assert "rollback apply" in rollback_history.read_text(encoding="utf-8")


def test_apply_rollback_rebuilds_plan_and_blocks_drift(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = latest_backup_id(registry)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    (target / "SKILL.md").write_text("# user drift\n", encoding="utf-8")

    with pytest.raises(RollbackApplyBlocked, match="plan_not_executable"):
        apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert "# user drift" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert not (registry / "state" / "rollback-history.jsonl").exists()


def test_apply_rollback_restores_managed_symlink_to_tree(fake_home):
    registry = fake_home / "agentmesh"
    backup = registry / "backups" / "20260430-120000-000001"
    backup_skill = backup / "openclaw" / "demo-skill"
    backup_skill.mkdir(parents=True)
    (backup_skill / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    history = registry / "state" / "sync-history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(
        '{"id":"sync-symlink","timestamp":"2026-04-30T12:00:00+00:00",'
        '"operation":"skills sync","status":"applied","targets":["openclaw"],'
        '"sync_mode":"symlink","summary":{"actions":1,"allowed":1,"blocked":0,"warnings":0},'
        f'"backup":"{backup}",'
        '"actions":[{"skill":"demo-skill","to":"openclaw","decision":"allow"}]}\n',
        encoding="utf-8",
    )
    make_registry_skill(registry, "demo-skill", "# linked registry source")
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(registry / "skills" / "demo-skill", target_is_directory=True)
    (target.parent / ".demo-skill.agentmesh-link.yaml").write_text(
        "schema: agentmesh.link-lock/v1\nskill: demo-skill\ntarget: openclaw\nmode: symlink\n",
        encoding="utf-8",
    )
    backup_id = latest_backup_id(registry)

    result = apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert result["status"] == "applied"
    assert not target.is_symlink()
    assert "# Old" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert not (target.parent / ".demo-skill.agentmesh-link.yaml").exists()


def test_apply_rollback_restores_current_target_when_copy_fails(fake_home, monkeypatch):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = latest_backup_id(registry)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"

    import shutil

    real_copytree = shutil.copytree
    calls = {"count": 0}

    def fail_on_restore_copytree(src, dst, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated restore copy failure")
        return real_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", fail_on_restore_copytree)

    with pytest.raises(RollbackApplyBlocked, match="apply_failed_recovered"):
        apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert "# V2" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert (target / ".agentmesh-lock.yaml").exists()
    assert not (registry / "state" / "rollback-history.jsonl").exists()


def test_apply_rollback_restores_current_target_when_history_write_fails(fake_home, monkeypatch):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = latest_backup_id(registry)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"

    from agentmesh.services import rollback_service

    def fail_history(*args, **kwargs):
        raise OSError("simulated history failure")

    monkeypatch.setattr(rollback_service, "_append_rollback_history", fail_history)

    with pytest.raises(RollbackApplyBlocked, match="apply_failed_recovered"):
        apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert "# V2" in (target / "SKILL.md").read_text(encoding="utf-8")


def test_apply_rollback_removes_created_target_when_missing_target_history_fails(
    fake_home, monkeypatch
):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# V1")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    make_registry_skill(registry, "demo-skill", "# V2")
    sync(registry, ["openclaw"], apply=True, allow_conflicts=True)
    backup_id = latest_backup_id(registry)
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    import shutil

    shutil.rmtree(target)

    from agentmesh.services import rollback_service

    def fail_history(*args, **kwargs):
        raise OSError("simulated history failure")

    monkeypatch.setattr(rollback_service, "_append_rollback_history", fail_history)

    with pytest.raises(RollbackApplyBlocked, match="apply_failed_recovered"):
        apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert not target.exists()
    assert not target.is_symlink()


def test_apply_rollback_restores_managed_symlink_and_link_lock_when_copy_fails(
    fake_home, monkeypatch
):
    registry = fake_home / "agentmesh"
    backup = registry / "backups" / "20260430-130000-000001"
    backup_skill = backup / "openclaw" / "demo-skill"
    backup_skill.mkdir(parents=True)
    (backup_skill / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    history = registry / "state" / "sync-history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(
        '{"id":"sync-symlink-copy-fail","timestamp":"2026-04-30T13:00:00+00:00",'
        '"operation":"skills sync","status":"applied","targets":["openclaw"],'
        '"sync_mode":"symlink","summary":{"actions":1,"allowed":1,"blocked":0,"warnings":0},'
        f'"backup":"{backup}",'
        '"actions":[{"skill":"demo-skill","to":"openclaw","decision":"allow"}]}\n',
        encoding="utf-8",
    )
    make_registry_skill(registry, "demo-skill", "# linked registry source")
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(registry / "skills" / "demo-skill", target_is_directory=True)
    link_lock = target.parent / ".demo-skill.agentmesh-link.yaml"
    link_lock.write_text(
        "schema: agentmesh.link-lock/v1\nskill: demo-skill\ntarget: openclaw\nmode: symlink\n",
        encoding="utf-8",
    )
    backup_id = latest_backup_id(registry)

    import shutil

    real_copytree = shutil.copytree
    calls = {"count": 0}

    def fail_on_restore_copytree(src, dst, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("simulated symlink restore failure")
        return real_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", fail_on_restore_copytree)

    with pytest.raises(RollbackApplyBlocked, match="apply_failed_recovered"):
        apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert target.is_symlink()
    assert target.readlink() == registry / "skills" / "demo-skill"
    assert link_lock.exists()
    assert "agentmesh.link-lock/v1" in link_lock.read_text(encoding="utf-8")


def test_apply_rollback_restores_managed_symlink_and_link_lock_when_history_fails(
    fake_home, monkeypatch
):
    registry = fake_home / "agentmesh"
    backup = registry / "backups" / "20260430-140000-000001"
    backup_skill = backup / "openclaw" / "demo-skill"
    backup_skill.mkdir(parents=True)
    (backup_skill / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    history = registry / "state" / "sync-history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(
        '{"id":"sync-symlink-history-fail","timestamp":"2026-04-30T14:00:00+00:00",'
        '"operation":"skills sync","status":"applied","targets":["openclaw"],'
        '"sync_mode":"symlink","summary":{"actions":1,"allowed":1,"blocked":0,"warnings":0},'
        f'"backup":"{backup}",'
        '"actions":[{"skill":"demo-skill","to":"openclaw","decision":"allow"}]}\n',
        encoding="utf-8",
    )
    make_registry_skill(registry, "demo-skill", "# linked registry source")
    target = fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(registry / "skills" / "demo-skill", target_is_directory=True)
    link_lock = target.parent / ".demo-skill.agentmesh-link.yaml"
    link_lock.write_text(
        "schema: agentmesh.link-lock/v1\nskill: demo-skill\ntarget: openclaw\nmode: symlink\n",
        encoding="utf-8",
    )
    backup_id = latest_backup_id(registry)

    from agentmesh.services import rollback_service

    def fail_history(*args, **kwargs):
        raise OSError("simulated history failure")

    monkeypatch.setattr(rollback_service, "_append_rollback_history", fail_history)

    with pytest.raises(RollbackApplyBlocked, match="apply_failed_recovered"):
        apply_rollback(registry, backup_id, confirm=True, home=fake_home)

    assert target.is_symlink()
    assert target.readlink() == registry / "skills" / "demo-skill"
    assert link_lock.exists()
    assert "agentmesh.link-lock/v1" in link_lock.read_text(encoding="utf-8")
