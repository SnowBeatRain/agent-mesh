"""MemoryMesh MVP 测试：scan/import/diff/list。"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.memory_service import (
    MemoryImportConflict,
    diff_memory,
    import_memory,
    list_imported_memories,
    scan_memory_files,
)

runner = CliRunner()


def _make_memory_files(fake_home: Path) -> None:
    """在 fake_home 下创建各 Agent 的记忆文件。"""
    # Hermes
    hermes_dir = fake_home / ".hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)
    (hermes_dir / "MEMORY.md").write_text("# Hermes Memory\n\nHermes context.", encoding="utf-8")
    (hermes_dir / "USER.md").write_text("# User Prefs\n\nName: Alice", encoding="utf-8")

    # OpenClaw
    oc_dir = fake_home / ".openclaw" / "workspace"
    oc_dir.mkdir(parents=True, exist_ok=True)
    (oc_dir / "MEMORY.md").write_text("# OpenClaw Memory\n\nOC context.", encoding="utf-8")

    # Codex
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "instructions.md").write_text("# Codex Instructions\n\nBe helpful.", encoding="utf-8")

    # Claude Code
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "CLAUDE.md").write_text("# Claude Code\n\nThink step by step.", encoding="utf-8")


# ── scan tests ─────────────────────────────────────────────

def test_scan_all_agents(fake_home):
    _make_memory_files(fake_home)
    assets = scan_memory_files(fake_home, "all")
    names = {(a.agent, a.name) for a in assets}
    assert ("hermes", "MEMORY.md") in names
    assert ("hermes", "USER.md") in names
    assert ("openclaw", "MEMORY.md") in names
    assert ("codex", "instructions.md") in names
    assert ("claude-code", "CLAUDE.md") in names
    assert len(assets) == 5


def test_scan_single_agent(fake_home):
    _make_memory_files(fake_home)
    assets = scan_memory_files(fake_home, "hermes")
    assert len(assets) == 2
    assert all(a.agent == "hermes" for a in assets)


def test_scan_missing_files_skipped(fake_home):
    """如果记忆文件不存在，应跳过而非报错。"""
    assets = scan_memory_files(fake_home, "all")
    assert len(assets) == 0


def test_scan_unknown_agent_raises(fake_home):
    try:
        scan_memory_files(fake_home, "unknown-agent")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "未知 agent" in str(exc)


def test_scan_asset_metadata(fake_home):
    _make_memory_files(fake_home)
    assets = scan_memory_files(fake_home, "hermes")
    mem = [a for a in assets if a.name == "MEMORY.md"][0]
    assert mem.format == "markdown"
    assert mem.size > 0
    assert len(mem.digest) == 64  # sha256 hex


# ── import tests ───────────────────────────────────────────

def test_import_and_list(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    registry.mkdir(parents=True, exist_ok=True)

    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    assets = scan_memory_files(fake_home, "hermes")
    for a in assets:
        import_memory(registry, a)

    memories = list_imported_memories(registry)
    names = {m["name"] for m in memories}
    assert "MEMORY.md" in names
    assert "USER.md" in names
    assert all(m["agent"] == "hermes" for m in memories)


def test_import_idempotent(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    assets = scan_memory_files(fake_home, "hermes")
    for a in assets:
        import_memory(registry, a)
    # second import should not raise
    for a in assets:
        import_memory(registry, a)
    memories = list_imported_memories(registry)
    assert len(memories) == 2


def test_import_dry_run(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    assets = scan_memory_files(fake_home, "hermes")
    preview = import_memory(registry, assets[0], dry_run=True)
    assert preview["would_write"] is True
    assert preview["conflict"] is False
    # Should not have actually created the file
    assert not (registry / "memories").exists()


def test_import_conflict_on_content_change(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    assets = scan_memory_files(fake_home, "hermes")
    for a in assets:
        import_memory(registry, a)

    # Modify source file
    (fake_home / ".hermes" / "MEMORY.md").write_text(
        "# Modified Hermes Memory\n\nNew content.", encoding="utf-8"
    )
    new_assets = scan_memory_files(fake_home, "hermes")
    modified = [a for a in new_assets if a.name == "MEMORY.md"][0]
    try:
        import_memory(registry, modified)
        assert False, "Should have raised MemoryImportConflict"
    except MemoryImportConflict as exc:
        assert "导入冲突" in str(exc)


# ── diff tests ─────────────────────────────────────────────

def test_diff_after_import(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    # Import both hermes and openclaw memories
    for agent in ["hermes", "openclaw"]:
        for a in scan_memory_files(fake_home, agent):
            import_memory(registry, a)

    result = diff_memory(registry, "hermes", "openclaw")
    assert result["summary"]["total_a"] == 2  # MEMORY.md + USER.md
    assert result["summary"]["total_b"] == 1  # MEMORY.md
    assert "MEMORY.md" in result["different"]  # same name, different content
    assert "USER.md" in result["only_in_a"]


def test_diff_single_memory_identical(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    # Import same content for both agents
    hermes_mem = scan_memory_files(fake_home, "hermes")[0]  # MEMORY.md
    # Create a matching openclaw MEMORY.md
    oc_mem = scan_memory_files(fake_home, "openclaw")[0]
    import_memory(registry, hermes_mem)
    import_memory(registry, oc_mem)

    # Now overwrite openclaw with same content as hermes
    (fake_home / ".openclaw" / "workspace" / "MEMORY.md").write_text(
        hermes_mem.content, encoding="utf-8"
    )
    oc_mem_new = scan_memory_files(fake_home, "openclaw")[0]
    # re-import
    target = registry / "memories" / "openclaw" / "MEMORY.md" / "content.md"
    target.write_text(oc_mem_new.content, encoding="utf-8")
    from agentmesh.utils.yaml_io import write_yaml
    write_yaml(
        target.parent / "agentmesh.memory.yaml",
        {
            "schema": "agentmesh.memory/v1",
            "agent": "openclaw",
            "name": "MEMORY.md",
            "source_path": str(oc_mem_new.source_path),
            "digest": oc_mem_new.digest,
            "format": oc_mem_new.format,
            "size": oc_mem_new.size,
        },
    )

    result = diff_memory(registry, "hermes", "openclaw", name="MEMORY.md")
    assert result["level"] == 0
    assert result["result"] == "identical"


def test_diff_single_memory_different(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    for agent in ["hermes", "openclaw"]:
        for a in scan_memory_files(fake_home, agent):
            import_memory(registry, a)

    result = diff_memory(registry, "hermes", "openclaw", name="MEMORY.md")
    assert result["level"] == 1
    assert result["result"] == "different"


def test_diff_single_memory_only_in_one(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    for a in scan_memory_files(fake_home, "hermes"):
        import_memory(registry, a)

    result = diff_memory(registry, "hermes", "openclaw", name="USER.md")
    assert result["level"] == 2
    assert result["result"] == "only_in_a"


def test_diff_single_not_found(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"
    from agentmesh.config.loader import ensure_layout
    ensure_layout(registry)

    result = diff_memory(registry, "hermes", "openclaw", name="NOPE.md")
    assert result["level"] == 0
    assert result["result"] == "not_found"


# ── CLI integration tests ──────────────────────────────────

def test_cli_memory_scan(fake_home):
    _make_memory_files(fake_home)
    result = runner.invoke(app, ["memory", "scan", "--agent", "hermes", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.memory-scan/v1"
    assert len(data["data"]["memories"]) == 2


def test_cli_memory_scan_all(fake_home):
    _make_memory_files(fake_home)
    result = runner.invoke(app, ["memory", "scan", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data["data"]["memories"]) == 5


def test_cli_memory_import_and_list(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"

    init = runner.invoke(app, ["init", "--registry", str(registry)])
    assert init.exit_code == 0, init.output

    imp = runner.invoke(app, ["memory", "import", "hermes", "--registry", str(registry), "--yes"])
    assert imp.exit_code == 0, imp.output
    assert "已导入 2 个" in imp.output

    lst = runner.invoke(app, ["memory", "list", "--registry", str(registry), "--json"])
    assert lst.exit_code == 0, lst.output
    data = json.loads(lst.output)
    assert len(data["data"]["memories"]) == 2


def test_cli_memory_import_dry_run(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"

    runner.invoke(app, ["init", "--registry", str(registry)])

    imp = runner.invoke(
        app, ["memory", "import", "hermes", "--registry", str(registry), "--dry-run"]
    )
    assert imp.exit_code == 0, imp.output
    assert "DRY-RUN" in imp.output


def test_cli_memory_diff(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"

    runner.invoke(app, ["init", "--registry", str(registry)])

    for agent in ["hermes", "openclaw"]:
        runner.invoke(
            app, ["memory", "import", agent, "--registry", str(registry), "--yes"]
        )

    diff = runner.invoke(
        app,
        ["memory", "diff", "hermes", "openclaw", "--registry", str(registry), "--json"],
    )
    assert diff.exit_code == 0, diff.output
    data = json.loads(diff.output)
    assert data["schema"] == "agentmesh.memory-diff/v1"
    assert "MEMORY.md" in data["data"]["different"]


def test_cli_memory_diff_single(fake_home):
    _make_memory_files(fake_home)
    registry = fake_home / "agentmesh-home"

    runner.invoke(app, ["init", "--registry", str(registry)])

    for agent in ["hermes", "openclaw"]:
        runner.invoke(
            app, ["memory", "import", agent, "--registry", str(registry), "--yes"]
        )

    diff = runner.invoke(
        app,
        [
            "memory", "diff", "hermes", "openclaw",
            "--name", "MEMORY.md",
            "--registry", str(registry), "--json",
        ],
    )
    assert diff.exit_code == 0, diff.output
    data = json.loads(diff.output)
    assert data["data"]["result"] == "different"


def test_cli_memory_scan_unknown_agent(fake_home):
    result = runner.invoke(app, ["memory", "scan", "--agent", "unknown", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
