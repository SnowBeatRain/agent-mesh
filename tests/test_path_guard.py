import pytest

from agentmesh.paths.guard import PathGuard, PathViolation


def test_path_guard_rejects_codex_system(tmp_path):
    guard = PathGuard(registry_root=tmp_path / "registry")
    with pytest.raises(PathViolation):
        guard.ensure_writable_target(tmp_path / ".codex" / "skills" / ".system" / "official")


def test_path_guard_rejects_path_escape(tmp_path):
    guard = PathGuard(registry_root=tmp_path / "registry")
    with pytest.raises(PathViolation):
        guard.ensure_inside(tmp_path / "registry", tmp_path / "outside" / "x")
