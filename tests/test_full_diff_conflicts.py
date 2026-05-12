from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.engine.conflict_resolver import ConflictLevel
from agentmesh.engine.diff_engine import diff_skill


def make_skill(
    root: Path, name: str, description: str, skill_body: str, extra: dict[str, str] | None = None
):
    skill = root / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{skill_body}\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: {description}\n",
        encoding="utf-8",
    )
    for rel, content in (extra or {}).items():
        path = skill / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return skill


def registry_root(home: Path) -> Path:
    return home / "skills"


def test_diff_classifies_metadata_and_file_tree_changes(fake_home):
    registry = fake_home / "agentmesh"
    make_skill(
        registry_root(registry), "demo-skill", "Registry desc", "# Same", {"references/a.md": "A"}
    )

    target_root = fake_home / ".hermes" / "skills" / "custom"
    make_skill(target_root, "demo-skill", "Target desc", "# Same", {"references/a.md": "A"})

    metadata = diff_skill(registry, "demo-skill", "hermes")
    assert metadata.level == ConflictLevel.METADATA_ONLY
    assert metadata.name == "METADATA_ONLY"
    assert any(change["path"] == "agentmesh.asset.yaml" for change in metadata.changes)

    (target_root / "demo-skill" / "references" / "b.md").write_text("B", encoding="utf-8")
    tree = diff_skill(registry, "demo-skill", "hermes")
    assert tree.level == ConflictLevel.MANUAL_REVIEW
    assert tree.name == "MANUAL_REVIEW"
    assert any(change["path"] == "references/b.md" for change in tree.changes)


def test_skills_list_conflicts_outputs_real_conflicts(fake_home):
    registry = fake_home / "agentmesh"
    make_skill(registry_root(registry), "same-skill", "Same", "# Same")
    make_skill(registry_root(registry), "changed-skill", "Changed", "# Registry")
    make_skill(registry_root(registry), "missing-skill", "Missing", "# Registry")

    target_root = fake_home / ".hermes" / "skills" / "custom"
    make_skill(target_root, "same-skill", "Same", "# Same")
    make_skill(target_root, "changed-skill", "Changed", "# Target")

    runner = CliRunner()
    text = runner.invoke(
        app, ["skills", "list", "--registry", str(registry), "--conflicts", "--target", "hermes"]
    )
    assert text.exit_code == 0, text.output
    assert "changed-skill" in text.output
    assert "CONTENT_CHANGED" in text.output
    assert "missing-skill" in text.output
    assert "STRUCTURE_CHANGED" in text.output
    assert "same-skill" not in text.output

    json_result = runner.invoke(
        app,
        [
            "skills",
            "list",
            "--registry",
            str(registry),
            "--conflicts",
            "--target",
            "hermes",
            "--json",
        ],
    )
    assert json_result.exit_code == 0, json_result.output
    data = json.loads(json_result.output)
    assert data["schema"] == "agentmesh.skills-list/v1"
    assert data["command"] == "skills list"
    assert data["status"] == "ok"
    conflicts = data["data"]["conflicts"]
    assert {item["skill"] for item in conflicts} == {"changed-skill", "missing-skill"}
    assert {item["level"] for item in conflicts} == {2, 3}
