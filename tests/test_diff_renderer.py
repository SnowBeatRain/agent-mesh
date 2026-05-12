"""测试 diff_renderer 模块的彩色 diff 输出功能。"""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from agentmesh.cli.diff_renderer import (
    render_content_diff,
    render_diff,
    render_file_changes,
    render_metadata_diff,
)
from agentmesh.engine.conflict_resolver import ConflictLevel, ConflictResult


@pytest.fixture()
def make_registry_skill():
    """创建 registry skill 的 fixture。"""

    def _make(registry: Path, name: str, body: str = "# Registry") -> Path:
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

    return _make


def _capture(fn, **kwargs) -> str:
    """调用渲染函数并捕获纯文本输出。"""
    console = Console(no_color=True, width=120, record=True)
    fn(console=console, **kwargs)
    return console.export_text()


# ── render_file_changes ─────────────────────────────────────

def test_render_file_changes_source_only():
    changes = [{"path": "new.md", "status": "source-only", "kind": "file-tree"}]
    output = _capture(render_file_changes, changes=changes)
    assert "新增" in output
    assert "new.md" in output


def test_render_file_changes_target_only():
    changes = [{"path": "old.md", "status": "target-only", "kind": "file-tree"}]
    output = _capture(render_file_changes, changes=changes)
    assert "删除" in output
    assert "old.md" in output


def test_render_file_changes_changed():
    changes = [{"path": "SKILL.md", "status": "changed", "kind": "entrypoint"}]
    output = _capture(render_file_changes, changes=changes)
    assert "修改" in output
    assert "SKILL.md" in output
    assert "entrypoint" in output


def test_render_file_changes_empty():
    output = _capture(render_file_changes, changes=[])
    assert "无文件差异" in output


def test_render_file_changes_missing_target():
    changes = [{"path": ".", "status": "missing-target", "kind": "structure"}]
    output = _capture(render_file_changes, changes=changes)
    assert "缺失" in output


# ── render_metadata_diff ─────────────────────────────────────

def test_render_metadata_diff_changed_field(tmp_path):
    src = tmp_path / "source.md"
    tgt = tmp_path / "target.md"
    src.write_text("---\nname: skill\ndescription: new desc\n---\n\nbody\n", encoding="utf-8")
    tgt.write_text("---\nname: skill\ndescription: old desc\n---\n\nbody\n", encoding="utf-8")
    output = _capture(render_metadata_diff, source_path=src, target_path=tgt)
    assert "description" in output
    assert "new desc" in output
    assert "old desc" in output


def test_render_metadata_diff_added_field(tmp_path):
    src = tmp_path / "source.md"
    tgt = tmp_path / "target.md"
    src.write_text("---\nname: skill\ntags: [a, b]\n---\n\nbody\n", encoding="utf-8")
    tgt.write_text("---\nname: skill\n---\n\nbody\n", encoding="utf-8")
    output = _capture(render_metadata_diff, source_path=src, target_path=tgt)
    assert "tags" in output
    assert "a, b" in output


def test_render_metadata_diff_removed_field(tmp_path):
    src = tmp_path / "source.md"
    tgt = tmp_path / "target.md"
    src.write_text("---\nname: skill\n---\n\nbody\n", encoding="utf-8")
    tgt.write_text("---\nname: skill\nold_field: val\n---\n\nbody\n", encoding="utf-8")
    output = _capture(render_metadata_diff, source_path=src, target_path=tgt)
    assert "old_field" in output
    assert "val" in output


def test_render_metadata_diff_no_change(tmp_path):
    src = tmp_path / "source.md"
    tgt = tmp_path / "target.md"
    src.write_text("---\nname: skill\n---\n\nbody\n", encoding="utf-8")
    tgt.write_text("---\nname: skill\n---\n\nbody\n", encoding="utf-8")
    console = Console(no_color=True, record=True)
    result = render_metadata_diff(src, tgt, console=console)
    assert result is False


def test_render_metadata_diff_missing_file(tmp_path):
    src = tmp_path / "source.md"
    tgt = tmp_path / "missing.md"
    src.write_text("---\nname: skill\n---\n\nbody\n", encoding="utf-8")
    console = Console(no_color=True, record=True)
    result = render_metadata_diff(src, tgt, console=console)
    assert result is False


# ── render_content_diff ──────────────────────────────────────

def test_render_content_diff_shows_changes(tmp_path):
    src = tmp_path / "source.md"
    tgt = tmp_path / "target.md"
    src.write_text("# New\n\nline 2\n", encoding="utf-8")
    tgt.write_text("# Old\n\nline 2\n", encoding="utf-8")
    output = _capture(render_content_diff, source_path=src, target_path=tgt, rel="SKILL.md")
    assert "-# Old" in output
    assert "+# New" in output


def test_render_content_diff_binary_skipped(tmp_path):
    src = tmp_path / "source.bin"
    tgt = tmp_path / "target.bin"
    src.write_bytes(b"\x00\x01\x02")
    tgt.write_bytes(b"\x03\x04\x05")
    output = _capture(render_content_diff, source_path=src, target_path=tgt, rel="data.bin")
    assert output.strip() == ""


# ── render_diff (top-level) ──────────────────────────────────

def test_render_diff_identical():
    result = ConflictResult(ConflictLevel.IDENTICAL, "IDENTICAL", "内容一致", [])
    console = Console(no_color=True, record=True)
    render_diff(result, Path("/fake/src"), Path("/fake/tgt"), console=console)
    output = console.export_text()
    assert "0" in output
    assert "IDENTICAL" in output
    assert "内容一致" in output


def test_render_diff_content_changed_with_changes():
    changes = [
        {"path": "SKILL.md", "status": "changed", "kind": "entrypoint"},
        {"path": "agentmesh.asset.yaml", "status": "changed", "kind": "metadata"},
    ]
    result = ConflictResult(
        ConflictLevel.CONTENT_CHANGED, "CONTENT_CHANGED", "内容不同", changes
    )
    console = Console(no_color=True, record=True)
    render_diff(result, Path("/fake/src"), Path("/fake/tgt"), console=console)
    output = console.export_text()
    assert "CONTENT_CHANGED" in output
    assert "文件差异" in output
    assert "SKILL.md" in output
    assert "修改" in output


def test_render_diff_structure_changed():
    changes = [{"path": ".", "status": "missing-target", "kind": "structure"}]
    result = ConflictResult(
        ConflictLevel.STRUCTURE_CHANGED, "STRUCTURE_CHANGED", "目标 skill 不存在", changes
    )
    console = Console(no_color=True, record=True)
    render_diff(result, Path("/fake/src"), Path("/fake/tgt"), console=console)
    output = console.export_text()
    assert "目标 skill 不存在" in output
    assert "缺失" in output


def test_render_diff_full_with_real_files(tmp_path):
    """端到端测试：带真实文件的完整 diff 渲染。"""
    source = tmp_path / "source_skill"
    target = tmp_path / "target_skill"
    source.mkdir()
    target.mkdir()

    # 写入不同的 SKILL.md
    (source / "SKILL.md").write_text(
        "---\nname: demo\ndescription: New version\n---\n\n# Demo Skill\n\nUpdated content.\n",
        encoding="utf-8",
    )
    (target / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Old version\n---\n\n# Demo Skill\n\nOld content.\n",
        encoding="utf-8",
    )
    # source 有一个额外文件
    (source / "helper.py").write_text("print('hello')\n", encoding="utf-8")

    changes = [
        {"path": "SKILL.md", "status": "changed", "kind": "entrypoint"},
        {"path": "SKILL.md", "status": "changed", "kind": "metadata"},
        {"path": "helper.py", "status": "source-only", "kind": "file-tree"},
    ]
    result = ConflictResult(
        ConflictLevel.CONTENT_CHANGED, "CONTENT_CHANGED", "内容不同", changes
    )

    console = Console(no_color=True, record=True)
    render_diff(result, source, target, console=console)
    output = console.export_text()

    # 文件级差异
    assert "文件差异" in output
    assert "修改" in output
    assert "新增" in output

    # metadata 差异
    assert "Metadata 差异" in output
    assert "description" in output
    assert "New version" in output
    assert "Old version" in output

    # 内容 diff
    assert "内容差异" in output
    assert "Updated content" in output or "Old content" in output


# ── 与 CLI 集成 ──────────────────────────────────────────────

def test_skills_diff_uses_color_renderer(fake_home, make_registry_skill):
    """确保 skills diff 命令使用彩色渲染器。"""
    from typer.testing import CliRunner

    from agentmesh.cli.main import app

    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "color-test", "# registry content")

    hermes_target = fake_home / ".hermes" / "skills" / "custom" / "color-test"
    hermes_target.mkdir(parents=True)
    (hermes_target / "SKILL.md").write_text(
        "---\nname: color-test\ndescription: Demo\n---\n\n# target changed\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["skills", "diff", "color-test", "--registry", str(registry), "--target", "hermes"],
    )
    assert result.exit_code == 0, result.output
    # 新渲染器应输出文件差异部分
    assert "文件差异" in result.output or "CONTENT_CHANGED" in result.output


def test_skills_diff_no_color_option(fake_home, make_registry_skill):
    """确保 --no-color 选项正常工作。"""
    from typer.testing import CliRunner

    from agentmesh.cli.main import app

    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "nocolor-test", "# registry")

    hermes_target = fake_home / ".hermes" / "skills" / "custom" / "nocolor-test"
    hermes_target.mkdir(parents=True)
    (hermes_target / "SKILL.md").write_text(
        "---\nname: nocolor-test\ndescription: Demo\n---\n\n# target changed\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "skills",
            "diff",
            "nocolor-test",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--no-color",
        ],
    )
    assert result.exit_code == 0, result.output
