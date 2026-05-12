"""Tests for P0-9: `skills rename` and `skills delete [--purge-targets]`."""

from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def _seed_registry_skill(registry: Path, name: str, body: str = "# body") -> Path:
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
    (skill / "agentmesh.skill.yaml").write_text(
        f"schema: agentmesh.skill/v1\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    (skill / "provenance.yaml").write_text(
        f"source_agent: hermes\nhash: abc123\nsource_path: /tmp/{name}\n",
        encoding="utf-8",
    )
    return skill


def test_rename_registry_skill_updates_dir_and_manifests(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "old-name")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "rename", "old-name", "new-name", "--registry", str(registry)],
    )

    assert result.exit_code == 0, result.output
    assert not (registry / "skills" / "old-name").exists()
    assert (registry / "skills" / "new-name" / "SKILL.md").exists()
    asset = (registry / "skills" / "new-name" / "agentmesh.asset.yaml").read_text(encoding="utf-8")
    manifest = (registry / "skills" / "new-name" / "agentmesh.skill.yaml").read_text(
        encoding="utf-8"
    )
    assert "name: new-name" in asset
    assert "name: new-name" in manifest


def test_rename_also_migrates_state_skills_yaml(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "old-name")
    runner = CliRunner()

    # 先启用一下，让 state/skills.yaml 里有 old-name 条目
    enable = runner.invoke(
        app,
        [
            "skills",
            "enable",
            "old-name",
            "--target",
            "openclaw",
            "--registry",
            str(registry),
        ],
    )
    assert enable.exit_code == 0, enable.output
    state_path = registry / "state" / "skills.yaml"
    assert state_path.exists()
    assert "old-name" in state_path.read_text(encoding="utf-8")

    # rename
    rename = runner.invoke(
        app,
        ["skills", "rename", "old-name", "new-name", "--registry", str(registry)],
    )
    assert rename.exit_code == 0, rename.output
    state_after = state_path.read_text(encoding="utf-8")
    assert "new-name" in state_after
    assert "old-name" not in state_after


def test_rename_refuses_when_new_name_exists(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "old-name")
    _seed_registry_skill(registry, "taken")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "rename", "old-name", "taken", "--registry", str(registry)],
    )

    assert result.exit_code != 0
    assert "已存在" in result.output
    # Both skills should still be intact
    assert (registry / "skills" / "old-name" / "SKILL.md").exists()
    assert (registry / "skills" / "taken" / "SKILL.md").exists()


def test_rename_rejects_invalid_new_name(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "old-name")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "rename", "old-name", "INVALID NAME!!", "--registry", str(registry)],
    )

    assert result.exit_code != 0
    assert (registry / "skills" / "old-name").exists()
    assert "Traceback" not in result.output


def test_rename_missing_old_name_errors_cleanly(fake_home):
    registry = fake_home / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "rename", "no-such-skill", "new-name", "--registry", str(registry)],
    )

    assert result.exit_code != 0
    assert "不存在" in result.output
    assert "Traceback" not in result.output


def test_delete_without_yes_aborts(fake_home):
    """delete 默认必须显式 --yes 或 -y；默认应退出且不删除任何东西。"""
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "doomed")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "delete", "doomed", "--registry", str(registry)],
    )

    assert result.exit_code != 0
    assert (registry / "skills" / "doomed" / "SKILL.md").exists()
    assert "yes" in result.output.lower() or "确认" in result.output


def test_delete_with_yes_removes_registry_entry(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "doomed")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "delete", "doomed", "--yes", "--registry", str(registry)],
    )

    assert result.exit_code == 0, result.output
    assert not (registry / "skills" / "doomed").exists()


def test_delete_purges_state_entry(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "doomed")
    runner = CliRunner()

    runner.invoke(
        app,
        ["skills", "enable", "doomed", "--target", "openclaw", "--registry", str(registry)],
    )
    state_path = registry / "state" / "skills.yaml"
    assert "doomed" in state_path.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        ["skills", "delete", "doomed", "--yes", "--registry", str(registry)],
    )
    assert result.exit_code == 0, result.output
    assert "doomed" not in state_path.read_text(encoding="utf-8")


def test_delete_purge_targets_removes_only_managed_copies(fake_home, monkeypatch):
    """--purge-targets 只删除带 AgentMesh lockfile 的 target 目录，
    不会触碰用户自己维护的同名目录。"""
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "shared")

    # 伪造两个 target 目录：
    # A) openclaw 上有 AgentMesh lockfile → 应被清理
    # B) hermes 上是用户自己维护的（没有 lockfile）→ 应被保留
    managed = fake_home / ".openclaw" / "workspace" / "skills" / "shared"
    managed.mkdir(parents=True)
    (managed / "SKILL.md").write_text("managed", encoding="utf-8")
    (managed / ".agentmesh-lock.yaml").write_text(
        "schema: agentmesh.lock/v1\nskill: shared\ntarget: openclaw\nhash: deadbeef\n",
        encoding="utf-8",
    )
    hand_rolled = fake_home / ".hermes" / "skills" / "custom" / "shared"
    hand_rolled.mkdir(parents=True)
    (hand_rolled / "SKILL.md").write_text("user-maintained", encoding="utf-8")

    # Pin loader.user_home() to fake_home so target_skill_path targets our fixtures
    import agentmesh.config.loader as loader_mod

    monkeypatch.setattr(loader_mod, "user_home", lambda: fake_home)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "skills",
            "delete",
            "shared",
            "--yes",
            "--purge-targets",
            "--registry",
            str(registry),
        ],
    )

    assert result.exit_code == 0, result.output
    assert not (registry / "skills" / "shared").exists()
    assert not managed.exists(), "managed copy should be purged"
    assert hand_rolled.exists(), "unmanaged user copy must be preserved"


def test_delete_missing_skill_errors_cleanly(fake_home):
    registry = fake_home / "agentmesh"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "delete", "no-such-skill", "--yes", "--registry", str(registry)],
    )
    assert result.exit_code != 0
    assert "不存在" in result.output
    assert "Traceback" not in result.output


def test_rename_then_sync_target_roundtrip(fake_home, monkeypatch):
    """rename 后跑一次 sync，应把新名字同步到 target；旧 managed 副本
    需要通过 `delete <old> --purge-targets` 清理（本测试不断言旧副本去向，
    只验证 rename+sync 不抛错）。"""
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "old-name")
    import agentmesh.config.loader as loader_mod

    monkeypatch.setattr(loader_mod, "user_home", lambda: fake_home)
    runner = CliRunner()

    init = runner.invoke(app, ["init", "--registry", str(registry)])
    assert init.exit_code == 0, init.output

    rename = runner.invoke(
        app,
        ["skills", "rename", "old-name", "renamed", "--registry", str(registry)],
    )
    assert rename.exit_code == 0, rename.output

    sync_result = runner.invoke(
        app,
        [
            "skills",
            "sync",
            "--to",
            "openclaw",
            "--apply",
            "--yes",
            "--registry",
            str(registry),
        ],
    )
    assert sync_result.exit_code == 0, sync_result.output
    assert (fake_home / ".openclaw" / "workspace" / "skills" / "renamed" / "SKILL.md").exists()
