from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def make_runtime(root: Path):
    skill = root / ".hermes" / "skills" / "custom" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill\n---\n\n# Demo\n", encoding="utf-8"
    )
    risky = root / ".codex" / "skills" / ".system" / "official"
    risky.mkdir(parents=True)
    (risky / "SKILL.md").write_text("---\nname: official\n---\n", encoding="utf-8")


def test_scan_import_audit_and_dry_run_flow(fake_home):
    make_runtime(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    init = runner.invoke(app, ["init", "--registry", str(registry)])
    assert init.exit_code == 0, init.output

    scan = runner.invoke(
        app, ["skills", "scan", "--registry", str(registry), "--agent", "all", "--json"]
    )
    assert scan.exit_code == 0, scan.output
    assert "demo-skill" in scan.output
    assert "official" not in scan.output

    imported = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])
    assert imported.exit_code == 0, imported.output
    assert (registry / "skills" / "demo-skill" / "agentmesh.asset.yaml").exists()

    audit = runner.invoke(app, ["audit", "all", "--registry", str(registry), "--json"])
    assert audit.exit_code == 0, audit.output
    assert "findings" in audit.output

    dry_run = runner.invoke(
        app, ["skills", "sync", "--registry", str(registry), "--to", "openclaw", "--dry-run"]
    )
    assert dry_run.exit_code == 0, dry_run.output
    assert "DRY-RUN" in dry_run.output
    assert not (fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill").exists()


def test_import_filters_generated_and_vcs_noise(fake_home):
    skill = fake_home / ".hermes" / "skills" / "custom" / "filtered-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: filtered-skill\ndescription: Filtered skill\n---\n\n# Filtered\n",
        encoding="utf-8",
    )
    (skill / "references").mkdir()
    (skill / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (skill / ".git" / "hooks").mkdir(parents=True)
    (skill / ".git" / "hooks" / "pre-receive.sample").write_text(
        "rm -rf /tmp/demo\n", encoding="utf-8"
    )
    (skill / "__pycache__").mkdir()
    (skill / "__pycache__" / "cached.pyc").write_bytes(b"cache")
    (skill / ".DS_Store").write_text("noise", encoding="utf-8")

    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    imported = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])

    assert imported.exit_code == 0, imported.output
    imported_skill = registry / "skills" / "filtered-skill"
    assert (imported_skill / "SKILL.md").exists()
    assert (imported_skill / "references" / "guide.md").exists()
    assert not (imported_skill / ".git").exists()
    assert not (imported_skill / "__pycache__").exists()
    assert not (imported_skill / ".DS_Store").exists()
    assert (imported_skill / "provenance.yaml").read_text(encoding="utf-8").count("excluded_count")


def test_import_blocks_same_name_with_different_content(fake_home):
    make_runtime(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    first = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])
    assert first.exit_code == 0, first.output

    skill_file = fake_home / ".hermes" / "skills" / "custom" / "demo-skill" / "SKILL.md"
    skill_file.write_text(
        "---\nname: demo-skill\ndescription: Demo skill\n---\n\n# Changed\n",
        encoding="utf-8",
    )

    second = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])

    assert second.exit_code != 0
    assert "导入冲突" in second.output
    assert "# Demo" in (registry / "skills" / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_import_idempotent_same_name_same_content(fake_home):
    """同名同内容重复 import 应幂等：不报错，不修改已有文件。"""
    make_runtime(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    first = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])
    assert first.exit_code == 0, first.output

    # 记录第一次导入后 registry 内容
    skill_dir = registry / "skills" / "demo-skill"
    original_content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    original_provenance = (skill_dir / "provenance.yaml").read_text(encoding="utf-8")
    original_asset = (skill_dir / "agentmesh.asset.yaml").read_text(encoding="utf-8")

    # 第二次导入同名同内容——应幂等成功
    second = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])
    assert second.exit_code == 0, second.output
    assert "已导入" in second.output

    # 内容应完全一致
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == original_content
    assert (skill_dir / "provenance.yaml").read_text(encoding="utf-8") == original_provenance
    assert (skill_dir / "agentmesh.asset.yaml").read_text(encoding="utf-8") == original_asset


def test_import_generated_metadata_not_in_content_conflict(fake_home):
    """AgentMesh 生成的 metadata（agentmesh.asset.yaml 等）不应影响内容冲突判断。

    冲突判断基于源 skill 的 digest（SKILL.md 的 sha256），
    而不是 registry 中已生成文件的内容。
    """
    make_runtime(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    first = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])
    assert first.exit_code == 0, first.output

    # 模拟有人手动修改了 registry 中 agentmesh 生成的 metadata
    skill_dir = registry / "skills" / "demo-skill"
    generated_asset = skill_dir / "agentmesh.asset.yaml"
    original_text = generated_asset.read_text(encoding="utf-8")
    generated_asset.write_text(original_text + "\n# tampered\n", encoding="utf-8")

    # 源 skill 未变——再次导入应幂等成功（不受 metadata 被篡改影响）
    second = runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])
    assert second.exit_code == 0, second.output


def test_import_service_level_dry_run(fake_home):
    """import_skill 传入 dry_run=True 时应预览导入结果而不实际写入。"""
    from agentmesh.services.registry_service import import_skill

    skill_src = fake_home / "source-skill"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text(
        "---\nname: dry-skill\ndescription: Dry run test\n---\n\n# Dry\n",
        encoding="utf-8",
    )

    from agentmesh.models.skill import NativeSkill
    from agentmesh.utils.hashing import hash_file

    entrypoint = skill_src / "SKILL.md"
    skill = NativeSkill(
        name="dry-skill",
        description="Dry run test",
        agent="hermes",
        source_path=skill_src,
        entrypoint=entrypoint,
        digest=hash_file(entrypoint),
    )

    registry = fake_home / "agentmesh-home"
    registry.mkdir(parents=True)

    # dry-run 应返回预览信息但不写入文件
    result = import_skill(registry, skill, dry_run=True)
    target = registry / "skills" / "dry-skill"
    assert not target.exists(), "dry-run 不应创建目标目录"
    assert result is not None, "dry-run 应返回预览信息"
    assert result["skill"] == "dry-skill"
    assert result["would_write"] is True
    assert result["conflict"] is False

    # 再导入一次（非 dry-run），然后 dry-run 预览同内容——应显示 would_write=False
    import_skill(registry, skill)
    assert target.exists()

    result2 = import_skill(registry, skill, dry_run=True)
    assert result2["would_write"] is False, "同内容幂等，不应写入"
    assert result2["conflict"] is False


def test_import_cli_dry_run(fake_home):
    """CLI skills import --dry-run 应预览导入而不实际写入。"""
    make_runtime(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    result = runner.invoke(
        app, ["skills", "import", "hermes", "--registry", str(registry), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert "demo-skill" in result.output
    # 不应实际创建 skill 目录
    assert not (registry / "skills" / "demo-skill").exists()


def test_scan_keeps_skill_with_invalid_frontmatter_as_warning(fake_home):
    skill = fake_home / ".claude" / "plugins" / "bad-frontmatter"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: bad-frontmatter\ndescription: broken: yaml\n---\n\n# Bad\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "scan", "--agent", "claude-code", "--json"])

    assert result.exit_code == 0, result.output
    assert "bad-frontmatter" in result.output
    assert "warnings" in result.output
    assert "frontmatter" in result.output



def test_import_unknown_agent_reports_supported_list(fake_home):
    """未知 agent 名应给出友好提示而不是 KeyError traceback。"""
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "import", "not-a-real-agent", "--registry", str(registry)],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "not-a-real-agent" in result.output
    # 支持列表中至少包含常见 agent 名，方便用户自我纠错
    assert "hermes" in result.output


def test_import_missing_agent_dir_hints_installation(fake_home):
    """agent 已知但原生目录不存在时，提示用户该 agent 可能未安装。"""
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    # 不预先创建 .openclaw/workspace/skills，直接导入
    result = runner.invoke(
        app,
        ["skills", "import", "openclaw", "--registry", str(registry)],
    )

    assert result.exit_code == 0, result.output
    assert "已导入 0 个 skill" in result.output
    # 关键提示：目录不存在 / agent 未安装（rich 可能换行，所以分两段匹配）
    assert "未检测到" in result.output
    assert "skill" in result.output
    assert "目录" in result.output
    assert "openclaw" in result.output


def test_sync_apply_prints_backup_path_on_success(fake_home):
    """sync --apply 成功后非 JSON 输出应额外打印 backup 路径和回滚提示。"""
    make_runtime(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    runner.invoke(app, ["init", "--registry", str(registry)])
    runner.invoke(app, ["skills", "import", "hermes", "--registry", str(registry)])

    # 首次 sync 到 openclaw：target 不存在 → allow，完成后应打印 backup 路径
    result = runner.invoke(
        app,
        [
            "skills",
            "sync",
            "--registry",
            str(registry),
            "--to",
            "openclaw",
            "--apply",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "sync 完成" in result.output
    assert "backup:" in result.output
    assert "agentmesh rollback plan" in result.output



def test_cursor_scan_parses_frontmatter_description(fake_home):
    """cursor .mdc 文件的 YAML frontmatter 应被解析为 description / name。"""
    rules_dir = fake_home / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "review-checklist.mdc").write_text(
        "---\n"
        "name: review-checklist\n"
        "description: Cursor review checklist with YAML frontmatter\n"
        "---\n\n# Checklist\n- step 1\n",
        encoding="utf-8",
    )
    # 无 frontmatter 的 .mdc：description 仍为空，name 回退到 stem
    (rules_dir / "plain.mdc").write_text("# plain content\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["skills", "scan", "--agent", "cursor", "--json"])

    assert result.exit_code == 0, result.output
    assert "review-checklist" in result.output
    assert "Cursor review checklist with YAML frontmatter" in result.output
    assert "plain" in result.output


def test_windsurf_scan_parses_frontmatter_description(fake_home):
    rules_dir = fake_home / ".windsurf" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "safe-edits.md").write_text(
        "---\nname: safe-edits\ndescription: Windsurf safety rules\n---\n\n# body\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["skills", "scan", "--agent", "windsurf", "--json"])

    assert result.exit_code == 0, result.output
    assert "safe-edits" in result.output
    assert "Windsurf safety rules" in result.output


def test_aider_scan_parses_frontmatter_but_keeps_legacy_description(fake_home):
    """aider 的 .aider.conventions.md 若带 frontmatter 则采用其 description，
    否则回退到旧 legacy 描述 'Aider coding conventions'。"""
    # 带 frontmatter 的情况
    (fake_home / ".aider.conventions.md").write_text(
        "---\nname: aider-conventions\ndescription: Custom aider conventions\n---\n\n# body\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["skills", "scan", "--agent", "aider", "--json"])
    assert result.exit_code == 0, result.output
    assert "Custom aider conventions" in result.output

    # 无 frontmatter 的情况：description 回退到 legacy 值
    (fake_home / ".aider.conventions.md").write_text("# plain\n", encoding="utf-8")
    result2 = runner.invoke(app, ["skills", "scan", "--agent", "aider", "--json"])
    assert result2.exit_code == 0, result2.output
    assert "Aider coding conventions" in result2.output
