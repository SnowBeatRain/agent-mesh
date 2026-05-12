from __future__ import annotations

from pathlib import Path

from agentmesh.services.package_service import export_agentmesh_package, import_agentmesh_package


def make_registry_skill(registry: Path, name: str = "demo-skill") -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: {name}\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.skill.yaml").write_text(
        f"schema: agentmesh.skill/v1\nname: {name}\ndescription: {name}\n",
        encoding="utf-8",
    )
    return skill


def test_import_package_apply_records_source_identity(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    target = tmp_path / "agentmesh-target"

    import_agentmesh_package(target, package, apply=True)

    manifest = (target / "skills" / "demo-skill" / "agentmesh.asset.yaml").read_text(
        encoding="utf-8"
    )
    assert "source:" in manifest
    assert "kind: agentmesh-package" in manifest
    assert "package_sha256:" in manifest
    assert "original_hash:" in manifest


def test_import_package_apply_backfills_source_identity_for_identical_target(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    target = tmp_path / "agentmesh-target"
    make_registry_skill(target, "demo-skill")

    import_agentmesh_package(target, package, apply=True)

    manifest = (target / "skills" / "demo-skill" / "agentmesh.asset.yaml").read_text(
        encoding="utf-8"
    )
    assert "source:" in manifest
    assert "kind: agentmesh-package" in manifest
