from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.package_service import (
    PackageError,
    export_agentmesh_package,
    import_agentmesh_package,
)


def make_registry_skill(
    registry: Path,
    name: str = "demo-skill",
    *,
    description: str = "Demo skill",
    body: str = "# Demo\n",
) -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: {description}\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.skill.yaml").write_text(
        f"schema: agentmesh.skill/v1\nname: {name}\ndescription: {description}\n",
        encoding="utf-8",
    )
    return skill


def test_export_agentmesh_package_builds_zip_layout(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    out = tmp_path / "dist" / "agentmesh-package.zip"

    result = export_agentmesh_package(registry, out)

    assert result["target"] == "agentmesh"
    assert result["out"] == str(out)
    assert result["skills"] == ["demo-skill"]
    with zipfile.ZipFile(out) as package:
        names = set(package.namelist())
        assert "package.yaml" in names
        assert "skills/demo-skill/SKILL.md" in names
        assert "skills/demo-skill/agentmesh.asset.yaml" in names
        assert "skills/demo-skill/agentmesh.skill.yaml" in names


def test_skills_export_agentmesh_cli(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    out = tmp_path / "agentmesh-package.zip"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "export",
            "agentmesh",
            "--registry",
            str(registry),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.skills-export/v1"
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["target"] == "agentmesh"
    assert data["skills"] == ["demo-skill"]
    assert out.exists()


def test_import_agentmesh_package_dry_run_and_apply(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    target = tmp_path / "agentmesh-target"

    plan = import_agentmesh_package(target, package, apply=False)

    assert plan["summary"]["create"] == 1
    assert plan["summary"]["blocked"] == 0
    assert plan["skills"][0]["action"] == "create"
    assert not (target / "skills" / "demo-skill").exists()

    applied = import_agentmesh_package(target, package, apply=True)

    assert applied["summary"]["imported"] == 1
    assert (target / "skills" / "demo-skill" / "SKILL.md").exists()


def test_skills_import_package_cli_dry_run_and_apply(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    target = tmp_path / "agentmesh-target"
    runner = CliRunner()

    dry_run = runner.invoke(
        app,
        [
            "skills",
            "import-package",
            str(package),
            "--registry",
            str(target),
            "--dry-run",
            "--json",
        ],
    )

    assert dry_run.exit_code == 0, dry_run.output
    dry_data = json.loads(dry_run.output)
    assert dry_data["status"] == "planned"
    assert dry_data["dry_run"] is True
    assert dry_data["data"]["plan"]["summary"]["create"] == 1
    assert not (target / "skills" / "demo-skill").exists()

    applied = runner.invoke(
        app,
        [
            "skills",
            "import-package",
            str(package),
            "--registry",
            str(target),
            "--apply",
            "--json",
        ],
    )

    assert applied.exit_code == 0, applied.output
    applied_data = json.loads(applied.output)
    assert applied_data["status"] == "applied"
    assert applied_data["data"]["plan"]["summary"]["imported"] == 1
    assert (target / "skills" / "demo-skill" / "SKILL.md").exists()


def test_import_package_rejects_unsafe_zip_paths(tmp_path):
    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
        archive.writestr("../evil.txt", "x")

    with pytest.raises(PackageError, match="unsafe zip path"):
        import_agentmesh_package(tmp_path / "agentmesh-target", package, apply=False)


def test_import_package_blocks_audit_findings(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "risky-skill", body="api_key=abc123\n")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    target = tmp_path / "agentmesh-target"

    plan = import_agentmesh_package(target, package, apply=False)

    assert plan["policy"]["allowed"] is False
    assert plan["summary"]["blocked"] == 1
    with pytest.raises(PackageError, match="package import blocked"):
        import_agentmesh_package(target, package, apply=True)
    assert not (target / "skills" / "risky-skill").exists()


def test_import_package_blocks_same_name_different_content(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill", body="# From package\n")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    target = tmp_path / "agentmesh-target"
    make_registry_skill(target, "demo-skill", body="# Existing\n")

    plan = import_agentmesh_package(target, package, apply=False)

    assert plan["summary"]["blocked"] == 1
    assert plan["skills"][0]["action"] == "blocked"
    assert plan["skills"][0]["reason"] == "same-name-different-content"
    with pytest.raises(PackageError, match="package import blocked"):
        import_agentmesh_package(target, package, apply=True)
    assert "# Existing" in (target / "skills" / "demo-skill" / "SKILL.md").read_text(
        encoding="utf-8"
    )


def test_inspect_agentmesh_package_reports_read_only_summary(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    target = tmp_path / "agentmesh-target"

    from agentmesh.services.package_service import inspect_agentmesh_package

    report = inspect_agentmesh_package(package)

    assert report["schema"] == "agentmesh.package-inspect/v1"
    assert report["package"] == str(package)
    assert report["package_schema"] == "agentmesh.package/v1"
    assert report["summary"]["skill_count"] == 1
    assert report["summary"]["file_count"] == 4
    assert report["manifest"]["skill_count"] == 1
    assert report["skills"] == [{"name": "demo-skill", "path": "skills/demo-skill"}]
    assert not target.exists()


def test_inspect_agentmesh_package_rejects_bad_zip(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "bad.zip"
    package.write_text("not a zip", encoding="utf-8")

    with pytest.raises(PackageError, match="无法读取 AgentMesh package"):
        inspect_agentmesh_package(package)


def test_inspect_agentmesh_package_rejects_unsafe_zip_path(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
        archive.writestr("../evil.txt", "x")

    with pytest.raises(PackageError, match="unsafe zip path"):
        inspect_agentmesh_package(package)


def test_inspect_agentmesh_package_requires_manifest(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "missing-manifest.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("skills/demo-skill/SKILL.md", "# Demo\n")

    with pytest.raises(PackageError, match="package 缺少 package.yaml"):
        inspect_agentmesh_package(package)


def test_package_inspect_cli_json_envelope(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    runner = CliRunner()

    result = runner.invoke(app, ["package", "inspect", str(package), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-inspect/v1"
    assert data["command"] == "package inspect"
    assert data["status"] == "ok"
    assert data["data"]["summary"]["skill_count"] == 1
    assert data["data"]["summary"]["file_count"] == 4
    assert data["warnings"] == [
        "inspect 只查看 package 内容；不等于 checksum verify、audit 或 policy 审查。"
    ]


def test_package_inspect_cli_bad_zip_returns_error_envelope(tmp_path):
    package = tmp_path / "bad.zip"
    package.write_text("not a zip", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["package", "inspect", str(package), "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-inspect/v1"
    assert data["status"] == "error"
    assert "无法读取 AgentMesh package" in data["errors"][0]


def test_package_inspect_cli_human_output(tmp_path):
    source = tmp_path / "agentmesh-source"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(source, package)
    runner = CliRunner()

    result = runner.invoke(app, ["package", "inspect", str(package)])

    assert result.exit_code == 0, result.output
    assert "Package:" in result.output
    assert "Schema: agentmesh.package/v1" in result.output
    assert "Skills: 1" in result.output
    assert "Files: 4" in result.output
    assert "demo-skill" in result.output
    assert "不等于 verify/audit" in result.output


def test_inspect_agentmesh_package_rejects_absolute_zip_path(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "absolute.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
        archive.writestr("/tmp/evil.txt", "x")

    with pytest.raises(PackageError, match="unsafe zip path"):
        inspect_agentmesh_package(package)


def test_inspect_agentmesh_package_rejects_windows_drive_zip_path(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "windows-drive.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
        archive.writestr("C:/temp/evil.txt", "x")

    with pytest.raises(PackageError, match="unsafe zip path"):
        inspect_agentmesh_package(package)


def test_inspect_agentmesh_package_rejects_symlink_entry(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "symlink.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
        info = zipfile.ZipInfo("skills/demo-skill/link")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "target")

    with pytest.raises(PackageError, match="unsafe zip path"):
        inspect_agentmesh_package(package)


def test_inspect_agentmesh_package_requires_agentmesh_package_schema(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "wrong-schema.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: other.schema/v1\n")

    with pytest.raises(PackageError, match="package.yaml schema"):
        inspect_agentmesh_package(package)


def test_package_inspect_cli_invalid_utf8_manifest_returns_error_envelope(tmp_path):
    package = tmp_path / "invalid-utf8-manifest.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", b"\xff\xfe\x00")
    runner = CliRunner()

    result = runner.invoke(app, ["package", "inspect", str(package), "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-inspect/v1"
    assert data["status"] == "error"
    assert "package.yaml 无效" in data["errors"][0]


def test_package_inspect_cli_malformed_yaml_manifest_returns_error_envelope(tmp_path):
    package = tmp_path / "malformed-yaml-manifest.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: [agentmesh.package/v1\n")
    runner = CliRunner()

    result = runner.invoke(app, ["package", "inspect", str(package), "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-inspect/v1"
    assert data["status"] == "error"
    assert "package.yaml 无效" in data["errors"][0]


def test_package_inspect_cli_non_mapping_manifest_returns_error_envelope(tmp_path):
    package = tmp_path / "non-mapping-manifest.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "[]\n")
    runner = CliRunner()

    result = runner.invoke(app, ["package", "inspect", str(package), "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-inspect/v1"
    assert data["status"] == "error"
    assert "package.yaml 无效" in data["errors"][0]


def test_inspect_agentmesh_package_rejects_backslash_traversal(tmp_path):
    from agentmesh.services.package_service import inspect_agentmesh_package

    package = tmp_path / "backslash-traversal.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
        archive.writestr("skills\\..\\evil.txt", "x")

    with pytest.raises(PackageError, match="unsafe zip path"):
        inspect_agentmesh_package(package)


def test_package_group_does_not_break_skills_export_import_package_cli(tmp_path):
    source = tmp_path / "agentmesh-source"
    target = tmp_path / "agentmesh-target"
    make_registry_skill(source, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    runner = CliRunner()

    export_result = runner.invoke(
        app,
        [
            "skills",
            "export",
            "agentmesh",
            "--registry",
            str(source),
            "--out",
            str(package),
            "--json",
        ],
    )
    assert export_result.exit_code == 0, export_result.output

    import_result = runner.invoke(
        app,
        [
            "skills",
            "import-package",
            str(package),
            "--registry",
            str(target),
            "--dry-run",
            "--json",
        ],
    )
    assert import_result.exit_code == 0, import_result.output
    data = json.loads(import_result.output)
    assert data["schema"] == "agentmesh.skills-import-package/v1"
    assert data["status"] == "planned"
    assert data["data"]["plan"]["summary"]["skills"] == 1
