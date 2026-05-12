from __future__ import annotations

from pathlib import Path

from agentmesh.services.update_check_service import build_update_check


def make_registry_skill(
    registry: Path,
    name: str,
    *,
    source: str | None = None,
) -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    manifest = [
        "schema: agentmesh.asset/v1",
        "kind: skill",
        f"name: {name}",
        f"description: {name}",
    ]
    if source == "package":
        manifest.extend(
            [
                "source:",
                "  kind: agentmesh-package",
                "  package_path: demo-package.zip",
                "  package_sha256: sha256:abc123",
                "  original_hash: def456",
            ]
        )
    (skill / "agentmesh.asset.yaml").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return skill


def test_update_check_reports_package_sourced_skills_without_network(tmp_path):
    registry = tmp_path / "agentmesh-home"
    make_registry_skill(registry, "package-skill", source="package")
    make_registry_skill(registry, "local-skill")

    result = build_update_check(registry)

    assert result["schema"] == "agentmesh.update-check/v1"
    assert result["network"] == "disabled"
    assert result["summary"] == {"total": 2, "candidate": 0, "unknown": 1, "skipped": 1}
    by_name = {item["name"]: item for item in result["skills"]}
    assert by_name["package-skill"]["status"] == "unknown"
    assert by_name["package-skill"]["reason"] == "network-disabled"
    assert by_name["package-skill"]["source"]["kind"] == "agentmesh-package"
    assert by_name["package-skill"]["remote_checked"] is False
    assert by_name["local-skill"]["status"] == "skipped"
    assert by_name["local-skill"]["reason"] == "no-source"
