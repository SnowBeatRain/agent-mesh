"""Tests for Runtime renderers: skill → native format conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentmesh.runtime.renderer import (
    AiderRenderer,
    CursorRenderer,
    OpenClawRenderer,
    SkillMarkdownRenderer,
    WindsurfRenderer,
    get_renderer,
)


@pytest.fixture
def registry_with_skills(tmp_path: Path):
    """Create a minimal registry with two skills."""
    registry = tmp_path / "registry"
    skills = registry / "skills"

    s1 = skills / "hello-skill"
    s1.mkdir(parents=True)
    (s1 / "SKILL.md").write_text(
        "---\nname: hello-skill\ndescription: Greeting skill\n"
        "---\n\nSay hello to the user politely.\n",
        encoding="utf-8",
    )
    (s1 / "agentmesh.asset.yaml").write_text(
        "schema: agentmesh.asset/v1\nkind: skill\nname: hello-skill\n",
        encoding="utf-8",
    )

    s2 = skills / "code-review"
    s2.mkdir(parents=True)
    (s2 / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: Review code\n"
        "---\n\nReview code for quality and security.\n",
        encoding="utf-8",
    )
    (s2 / "agentmesh.asset.yaml").write_text(
        "schema: agentmesh.asset/v1\nkind: skill\nname: code-review\n",
        encoding="utf-8",
    )

    return registry


def _metadata(registry: Path, target: str, loader_dir: str = "") -> dict:
    return {
        "plan_id": "rtlp-abc123",
        "generated_at": "2026-05-03T12:00:00+00:00",
        "target": target,
        "registry": str(registry),
        "blocked": 0,
        "loader_dir": loader_dir,
    }


# --- SkillMarkdownRenderer (Hermes) ---


def test_hermes_renderer_produces_skill_md(registry_with_skills: Path, tmp_path: Path):
    loader_dir = tmp_path / "loader"
    loader_dir.mkdir()
    renderer = SkillMarkdownRenderer()
    payloads = renderer.render(
        registry_with_skills,
        ["hello-skill", "code-review"],
        _metadata(registry_with_skills, "hermes", str(loader_dir)),
    )
    assert len(payloads) == 1
    p = payloads[0]
    assert p.path.name == "SKILL.md"
    assert p.overwrite is True
    content = p.content
    assert "# AgentMesh Auto-Loaded Skills" in content
    assert "## hello-skill" in content
    assert "## code-review" in content
    assert "Say hello" in content
    assert "Review code" in content
    assert "rtlp-abc123" in content
    assert "agentmesh runtime disable" in content


def test_hermes_renderer_handles_empty_skills(registry_with_skills: Path, tmp_path: Path):
    loader_dir = tmp_path / "loader"
    loader_dir.mkdir()
    renderer = SkillMarkdownRenderer()
    payloads = renderer.render(
        registry_with_skills,
        [],
        _metadata(registry_with_skills, "hermes", str(loader_dir)),
    )
    assert len(payloads) == 1
    assert "Allowed: 0 skills" in payloads[0].content


# --- OpenClawRenderer ---


def test_openclaw_renderer_uses_same_format(registry_with_skills: Path, tmp_path: Path):
    loader_dir = tmp_path / "loader"
    loader_dir.mkdir()
    renderer = OpenClawRenderer()
    payloads = renderer.render(
        registry_with_skills,
        ["hello-skill"],
        _metadata(registry_with_skills, "openclaw", str(loader_dir)),
    )
    assert len(payloads) == 1
    assert payloads[0].path.name == "SKILL.md"
    assert "## hello-skill" in payloads[0].content


# --- CursorRenderer ---


def test_cursor_renderer_produces_mdc_file(registry_with_skills: Path, tmp_path: Path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    renderer = CursorRenderer()
    meta = _metadata(registry_with_skills, "cursor")
    meta["rules_dir"] = str(rules_dir)
    payloads = renderer.render(
        registry_with_skills,
        ["hello-skill", "code-review"],
        meta,
    )
    assert len(payloads) == 1
    p = payloads[0]
    assert p.path.name == "agentmesh-rules.mdc"
    content = p.content
    # Cursor .mdc has YAML frontmatter
    assert "---" in content
    assert "description:" in content
    assert "alwaysApply: true" in content
    assert "## hello-skill" in content
    assert "## code-review" in content


# --- WindsurfRenderer ---


def test_windsurf_renderer_produces_md_file(registry_with_skills: Path, tmp_path: Path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    renderer = WindsurfRenderer()
    meta = _metadata(registry_with_skills, "windsurf")
    meta["rules_dir"] = str(rules_dir)
    payloads = renderer.render(
        registry_with_skills,
        ["hello-skill"],
        meta,
    )
    assert len(payloads) == 1
    assert payloads[0].path.name == "agentmesh-rules.md"
    assert "## hello-skill" in payloads[0].content


# --- AiderRenderer ---


def test_aider_renderer_produces_conventions(registry_with_skills: Path, tmp_path: Path):
    conv_path = tmp_path / ".aider.conventions.md"
    renderer = AiderRenderer()
    meta = _metadata(registry_with_skills, "aider")
    meta["conventions_path"] = str(conv_path)
    payloads = renderer.render(
        registry_with_skills,
        ["hello-skill"],
        meta,
    )
    assert len(payloads) == 1
    assert payloads[0].path == conv_path
    assert "## hello-skill" in payloads[0].content


# --- get_renderer ---


def test_get_renderer_returns_correct_type():
    assert isinstance(get_renderer("hermes"), SkillMarkdownRenderer)
    assert isinstance(get_renderer("openclaw"), OpenClawRenderer)
    assert isinstance(get_renderer("cursor"), CursorRenderer)
    assert isinstance(get_renderer("windsurf"), WindsurfRenderer)
    assert isinstance(get_renderer("aider"), AiderRenderer)


def test_get_renderer_returns_none_for_unknown():
    assert get_renderer("codex") is None
    assert get_renderer("claude-code") is None
    assert get_renderer("nonexistent") is None


# --- entrypoint_path ---


def test_entrypoint_paths_are_correct(tmp_path: Path):
    assert SkillMarkdownRenderer().entrypoint_path(tmp_path) == tmp_path / "SKILL.md"
    assert CursorRenderer().entrypoint_path(tmp_path) == tmp_path.parent / "agentmesh-rules.mdc"
    assert WindsurfRenderer().entrypoint_path(tmp_path) == tmp_path.parent / "agentmesh-rules.md"
