"""Phase A1: 验证 AGENT_TARGETS 与 EXPORT_ONLY_TARGETS 的完整矩阵。

本测试文件确保：
- AGENT_TARGETS 覆盖全部 7 个 adapter（aider / claude-code 已补齐）。
- EXPORT_ONLY_TARGETS 至少包含 claude-code。
- `skills sync --apply --to claude-code` 被明确拦截，引导用户到 export 流程。
- `skills sync --dry-run --to aider` 能正常走通，不再报 unsupported target。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentmesh.config.loader import (
    AGENT_TARGETS,
    EXPORT_ONLY_TARGETS,
    ensure_layout,
    resolve_agentmesh_home,
)
from agentmesh.services.sync_service import (
    UnsupportedSyncMode,
    render_sync_plan,
    sync,
)

ALL_RUNTIME_NAMES = {
    "hermes",
    "openclaw",
    "codex",
    "claude-code",
    "cursor",
    "windsurf",
    "aider",
}


def test_agent_targets_covers_all_runtime_adapters():
    """AGENT_TARGETS 必须覆盖所有 7 个 adapter，便于 diff/enable 矩阵对齐。"""
    assert set(AGENT_TARGETS.keys()) == ALL_RUNTIME_NAMES


def test_export_only_targets_contains_claude_code():
    """claude-code 必须在 export-only 名单内，保持 MVP 安全契约。"""
    assert "claude-code" in EXPORT_ONLY_TARGETS


def test_aider_target_path_points_to_skills_dir():
    """aider 新增的 skill 目录路径约定应为 `~/.aider/skills/`。"""
    parts = AGENT_TARGETS["aider"]
    assert parts == (".aider", "skills")


def test_claude_code_target_path_points_to_plugins():
    """claude-code 的 plugin 目录 `~/.claude/plugins/` 登记在 AGENT_TARGETS。"""
    parts = AGENT_TARGETS["claude-code"]
    assert parts == (".claude", "plugins")


def test_sync_apply_to_export_only_target_is_blocked(tmp_path: Path):
    """直接对 claude-code 执行 sync --apply 必须被拦截，并给出引导。"""
    home = resolve_agentmesh_home(str(tmp_path / "registry"))
    ensure_layout(home)
    fake_user_home = tmp_path / "userhome"
    fake_user_home.mkdir()

    with pytest.raises(UnsupportedSyncMode) as excinfo:
        sync(home, ["claude-code"], apply=True, home=fake_user_home)

    message = str(excinfo.value)
    assert "claude-code" in message
    assert "export-only" in message
    assert "skills export" in message


def test_sync_apply_mixed_targets_blocks_when_any_is_export_only(tmp_path: Path):
    """列表中只要有 export-only 目标，apply 整体就应被拦截。"""
    home = resolve_agentmesh_home(str(tmp_path / "registry"))
    ensure_layout(home)
    fake_user_home = tmp_path / "userhome"
    fake_user_home.mkdir()

    with pytest.raises(UnsupportedSyncMode):
        sync(home, ["hermes", "claude-code"], apply=True, home=fake_user_home)


def test_sync_dry_run_to_export_only_target_is_allowed(tmp_path: Path):
    """dry-run 对 export-only 目标仍允许，方便用户预览。"""
    home = resolve_agentmesh_home(str(tmp_path / "registry"))
    ensure_layout(home)
    fake_user_home = tmp_path / "userhome"
    fake_user_home.mkdir()

    plan = sync(
        home,
        ["claude-code"],
        apply=False,
        home=fake_user_home,
    )
    assert plan["mode"] == "DRY-RUN"
    assert "summary" in plan


def test_sync_dry_run_to_aider_produces_plan(tmp_path: Path):
    """aider 新目标必须能正常 dry-run，不再报 unsupported target。"""
    home = resolve_agentmesh_home(str(tmp_path / "registry"))
    ensure_layout(home)
    fake_user_home = tmp_path / "userhome"
    fake_user_home.mkdir()

    plan = render_sync_plan(
        home,
        ["aider"],
        mode="DRY-RUN",
        home=fake_user_home,
    )
    assert plan["mode"] == "DRY-RUN"
    assert "summary" in plan
