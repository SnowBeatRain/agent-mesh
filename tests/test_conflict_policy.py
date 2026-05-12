from __future__ import annotations

from pathlib import Path

import pytest

from agentmesh.services.sync_service import SyncBlocked, sync


def make_registry_skill(registry: Path, name: str, body: str) -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    return skill


def make_runtime_skill(home: Path, name: str, body: str) -> Path:
    skill = home / ".openclaw" / "workspace" / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    return skill


def test_apply_blocks_content_conflict_by_default(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Registry\n")
    make_runtime_skill(fake_home, "demo-skill", "# Runtime\n")

    with pytest.raises(SyncBlocked, match="conflict"):
        sync(registry, ["openclaw"], apply=True)

    assert "# Runtime" in (
        fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill" / "SKILL.md"
    ).read_text(encoding="utf-8")


def test_apply_allows_content_conflict_when_explicitly_enabled(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Registry\n")
    make_runtime_skill(fake_home, "demo-skill", "# Runtime\n")

    result = sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    assert result["mode"] == "APPLY"
    assert result["summary"]["blocked"] == 1
    assert "# Registry" in (
        fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill" / "SKILL.md"
    ).read_text(encoding="utf-8")


def test_apply_never_allows_security_block_even_with_conflict_override(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "unsafe-skill", "api_key = 'SHOULD_NOT_LEAK'\n")

    with pytest.raises(SyncBlocked, match="security"):
        sync(registry, ["openclaw"], apply=True, allow_conflicts=True)


def test_cli_apply_supports_allow_conflicts_option(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# Registry\n")
    make_runtime_skill(fake_home, "demo-skill", "# Runtime\n")

    result = sync(registry, ["openclaw"], apply=True, allow_conflicts=True)

    assert result["mode"] == "APPLY"
    assert "# Registry" in (
        fake_home / ".openclaw" / "workspace" / "skills" / "demo-skill" / "SKILL.md"
    ).read_text(encoding="utf-8")
