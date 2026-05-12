"""Phase A5: 结构化 diff 引擎与 /skills/<name>*, /skills/diff/<name> 端点。

确保：
- `diff_skill_detailed()` 返回 per-file 结构化信息（status / kind / hunks / hashes）。
- 文本文件 diff 包含 unified hunks，每行标注 context / delete / insert。
- 二进制文件（含 null byte）被识别为 binary=True，不泄露正文。
- SKILL.md 的 YAML frontmatter 不进入 hunks，避免噪音与重复。
- Security-block 情况下不输出正文，只保留 blocked_reasons。
- Local API GET /skills/<name> 和 GET /skills/diff/<name>?target=<agent> 可用。
- 顶层 ConflictLevel / level_name 与旧 `diff_skill()` 对齐。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentmesh.config import loader
from agentmesh.config.loader import (
    AGENT_TARGETS,
    ensure_layout,
    resolve_agentmesh_home,
)
from agentmesh.engine.diff_engine import diff_skill, diff_skill_detailed
from agentmesh.local_api.service import handle_readonly_request
from agentmesh.models.skill import NativeSkill
from agentmesh.services.registry_service import import_skill

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_home_fixture(tmp_path: Path, monkeypatch):
    fake = tmp_path / "userhome"
    fake.mkdir()
    monkeypatch.setattr(loader, "user_home", lambda: fake)
    return fake


@pytest.fixture()
def home_with_skill(tmp_path: Path, fake_home_fixture: Path):
    """Registry with a single 'demo' skill imported from hermes."""
    home = resolve_agentmesh_home(str(tmp_path / "agentmesh-home"))
    ensure_layout(home)

    source = tmp_path / "source" / "demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill.\n---\n\n"
        "# Demo\n\nLine one\nLine two\nLine three\n",
        encoding="utf-8",
    )
    (source / "README.md").write_text("shared docs\n", encoding="utf-8")
    native = NativeSkill(
        name="demo",
        description="Demo skill.",
        agent="hermes",
        source_path=source,
        entrypoint=source / "SKILL.md",
        digest="digest-demo",
    )
    import_skill(home, native)
    return home


def _make_target_skill(fake_home: Path, agent: str, name: str, files: dict[str, str]) -> Path:
    """Create a fake target-runtime skill directory under fake_home."""
    parts = AGENT_TARGETS[agent]
    target_dir = fake_home.joinpath(*parts, name)
    target_dir.mkdir(parents=True)
    for rel, content in files.items():
        path = target_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return target_dir


# ── Engine-level tests ───────────────────────────────────────────────────


def test_diff_detailed_missing_target_returns_structure_change(
    home_with_skill: Path, fake_home_fixture: Path
):
    """Target runtime has no such skill → STRUCTURE_CHANGED + target-only files."""
    result = diff_skill_detailed(home_with_skill, "demo", "hermes")

    legacy = diff_skill(home_with_skill, "demo", "hermes")
    assert result["level"] == int(legacy.level)
    assert result["level_name"] == legacy.name
    assert result["summary"] == legacy.summary
    assert result["skill"] == "demo"
    assert result["target"] == "hermes"
    assert result["blocked"] is False
    assert result["blocked_reasons"] == []

    # Every non-lock registry file should show up as source-only
    paths = {entry["path"] for entry in result["files"]}
    assert "SKILL.md" in paths
    assert "README.md" in paths
    # Status must be source-only for missing target
    for entry in result["files"]:
        assert entry["status"] == "source-only"


def test_diff_detailed_identical_target_returns_empty_files(
    home_with_skill: Path, fake_home_fixture: Path
):
    """Mirror the registry into hermes → IDENTICAL + no file entries."""
    # Read back what the registry wrote for this skill and mirror it exactly.
    registry_skill = home_with_skill / "skills" / "demo"
    files = {
        p.relative_to(registry_skill).as_posix(): p.read_bytes()
        for p in registry_skill.rglob("*")
        if p.is_file() and p.name != ".agentmesh-lock.yaml"
    }
    _make_target_skill(fake_home_fixture, "hermes", "demo", files)

    result = diff_skill_detailed(home_with_skill, "demo", "hermes")
    assert result["level_name"] == "IDENTICAL"
    assert result["files"] == []


def test_diff_detailed_skill_md_body_changed_produces_unified_hunks(
    home_with_skill: Path, fake_home_fixture: Path
):
    """Modify the body of SKILL.md in hermes, expect CONTENT_CHANGED with hunks."""
    registry_skill = home_with_skill / "skills" / "demo"
    mirror = {
        p.relative_to(registry_skill).as_posix(): p.read_bytes()
        for p in registry_skill.rglob("*")
        if p.is_file() and p.name != ".agentmesh-lock.yaml"
    }
    # Edit SKILL.md body (not frontmatter).
    mirror["SKILL.md"] = (
        b"---\nname: demo\ndescription: Demo skill.\n---\n\n"
        b"# Demo\n\nLine one\nLine two CHANGED\nLine three\n"
    )
    _make_target_skill(fake_home_fixture, "hermes", "demo", mirror)

    result = diff_skill_detailed(home_with_skill, "demo", "hermes")
    assert result["level_name"] == "CONTENT_CHANGED"
    skill_entry = next(e for e in result["files"] if e["path"] == "SKILL.md")
    assert skill_entry["status"] == "changed"
    assert skill_entry["binary"] is False
    assert skill_entry["hunks"]
    all_types: list[str] = []
    for hunk in skill_entry["hunks"]:
        for line in hunk["lines"]:
            all_types.append(line["type"])
    assert "insert" in all_types
    assert "delete" in all_types


def test_diff_detailed_strips_skill_md_frontmatter_from_hunks(
    home_with_skill: Path, fake_home_fixture: Path
):
    """Frontmatter differences alone must not produce SKILL.md hunks."""
    registry_skill = home_with_skill / "skills" / "demo"
    mirror = {
        p.relative_to(registry_skill).as_posix(): p.read_bytes()
        for p in registry_skill.rglob("*")
        if p.is_file() and p.name != ".agentmesh-lock.yaml"
    }
    # Change only the frontmatter; body identical.
    mirror["SKILL.md"] = (
        b"---\nname: demo\ndescription: Different description here.\n---\n\n"
        b"# Demo\n\nLine one\nLine two\nLine three\n"
    )
    _make_target_skill(fake_home_fixture, "hermes", "demo", mirror)

    result = diff_skill_detailed(home_with_skill, "demo", "hermes")
    # Since our semantic hash strips frontmatter before comparison, the SKILL.md
    # body is identical → no SKILL.md entry in files (it only appears when
    # hashes differ on body).
    skill_md_entries = [e for e in result["files"] if e["path"] == "SKILL.md"]
    assert skill_md_entries == []


def test_diff_detailed_binary_file_marked_and_no_hunks(
    home_with_skill: Path, fake_home_fixture: Path
):
    """Binary file in target must be marked binary=True with hunks=None."""
    registry_skill = home_with_skill / "skills" / "demo"
    # Add a binary file to the registry side, by writing directly.
    (registry_skill / "blob.bin").write_bytes(b"\x00\x01\x02\x03binary\x00payload")

    mirror = {
        p.relative_to(registry_skill).as_posix(): p.read_bytes()
        for p in registry_skill.rglob("*")
        if p.is_file() and p.name != ".agentmesh-lock.yaml"
    }
    # Change the binary content on the target side.
    mirror["blob.bin"] = b"\x00\x01\x02\x03OTHER\x00payload"
    _make_target_skill(fake_home_fixture, "hermes", "demo", mirror)

    result = diff_skill_detailed(home_with_skill, "demo", "hermes")
    blob_entry = next(e for e in result["files"] if e["path"] == "blob.bin")
    assert blob_entry["binary"] is True
    assert blob_entry["hunks"] is None


def test_diff_detailed_security_block_redacts_file_content(tmp_path: Path, fake_home_fixture: Path):
    """Secrets in source must produce SECURITY_BLOCK with no hunks."""
    home = resolve_agentmesh_home(str(tmp_path / "agentmesh-home"))
    ensure_layout(home)

    source = tmp_path / "source" / "risky"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: risky\ndescription: Secret-bearing skill.\n---\n\n"
        'api_key = "SUPER_SECRET_123"\n',
        encoding="utf-8",
    )
    native = NativeSkill(
        name="risky",
        description="Secret-bearing skill.",
        agent="hermes",
        source_path=source,
        entrypoint=source / "SKILL.md",
        digest="digest-risky",
    )
    import_skill(home, native)

    # Ensure target exists (so we don't bail out with STRUCTURE_CHANGED)
    registry_skill = home / "skills" / "risky"
    mirror = {
        p.relative_to(registry_skill).as_posix(): p.read_bytes()
        for p in registry_skill.rglob("*")
        if p.is_file() and p.name != ".agentmesh-lock.yaml"
    }
    _make_target_skill(fake_home_fixture, "hermes", "risky", mirror)

    result = diff_skill_detailed(home, "risky", "hermes")
    assert result["level_name"] == "SECURITY_BLOCK"
    assert result["blocked"] is True
    assert "security" in result["blocked_reasons"]
    joined = str(result)
    assert "SUPER_SECRET_123" not in joined


def test_diff_detailed_rejects_unknown_target(home_with_skill: Path):
    with pytest.raises(ValueError):
        diff_skill_detailed(home_with_skill, "demo", "definitely-not-a-target")


# ── Local API endpoint tests ─────────────────────────────────────────────


def test_local_api_skills_detail_returns_rich_payload(
    home_with_skill: Path, fake_home_fixture: Path
):
    response = handle_readonly_request("GET", "/skills/demo", registry=home_with_skill)
    assert response["schema"] == "agentmesh.local-api-response/v1"
    assert response["command"] == "local-api skills detail"
    assert response["status"] == "ok"
    data = response["data"]
    assert data["skill"]["name"] == "demo"
    assert data["skill"]["file_count"] >= 2
    assert data["enabled_targets"] == []
    assert data["risk_summary"]["findings"] >= 0


def test_local_api_skills_detail_with_targets_query(home_with_skill: Path, fake_home_fixture: Path):
    response = handle_readonly_request(
        "GET",
        "/skills/demo?targets=hermes,openclaw",
        registry=home_with_skill,
    )
    assert response["status"] == "ok"
    data = response["data"]
    assert set(data["last_diff"]) == {"hermes", "openclaw"}


def test_local_api_skills_detail_missing_skill_returns_error(
    home_with_skill: Path, fake_home_fixture: Path
):
    response = handle_readonly_request(
        "GET", "/skills/definitely-missing", registry=home_with_skill
    )
    assert response["command"] == "local-api skills detail"
    assert response["status"] == "error"
    assert response["errors"]


def test_local_api_skills_diff_missing_target_returns_error(
    home_with_skill: Path, fake_home_fixture: Path
):
    """Without ?target=… the endpoint should reject with helpful guidance."""
    response = handle_readonly_request("GET", "/skills/diff/demo", registry=home_with_skill)
    assert response["command"] == "local-api skills diff"
    assert response["status"] == "error"
    assert response["errors"] == ["missing query parameter: target"]
    assert response["next_steps"]


def test_local_api_skills_diff_returns_structured_hunks(
    home_with_skill: Path, fake_home_fixture: Path
):
    registry_skill = home_with_skill / "skills" / "demo"
    mirror = {
        p.relative_to(registry_skill).as_posix(): p.read_bytes()
        for p in registry_skill.rglob("*")
        if p.is_file() and p.name != ".agentmesh-lock.yaml"
    }
    mirror["README.md"] = b"changed docs\n"
    _make_target_skill(fake_home_fixture, "hermes", "demo", mirror)

    response = handle_readonly_request(
        "GET", "/skills/diff/demo?target=hermes", registry=home_with_skill
    )
    assert response["status"] == "ok"
    data = response["data"]
    assert data["skill"] == "demo"
    assert data["target"] == "hermes"
    readme_entry = next(e for e in data["files"] if e["path"] == "README.md")
    assert readme_entry["status"] == "changed"
    assert readme_entry["binary"] is False
    assert readme_entry["hunks"]


def test_local_api_skills_diff_unknown_target_returns_error(
    home_with_skill: Path, fake_home_fixture: Path
):
    response = handle_readonly_request(
        "GET", "/skills/diff/demo?target=bogus-agent", registry=home_with_skill
    )
    assert response["status"] == "error"
    assert response["errors"]
