from __future__ import annotations

import json
import shutil
import zipfile

from tests.test_package_service import make_registry_skill
from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.package_service import (
    export_agentmesh_package,
    verify_agentmesh_package,
)


def test_export_agentmesh_package_writes_manifest_checksums(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"

    export_agentmesh_package(registry, package)

    with zipfile.ZipFile(package) as archive:
        manifest = archive.read("package.yaml").decode("utf-8")
    assert "files:" in manifest
    assert "path: skills/demo-skill/SKILL.md" in manifest
    assert "sha256:" in manifest


def test_verify_agentmesh_package_accepts_valid_export(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(registry, package)

    report = verify_agentmesh_package(package)

    assert report["schema"] == "agentmesh.package-verify/v1"
    assert report["package"] == str(package)
    assert report["valid"] is True
    assert report["summary"] == {
        "declared_files": 3,
        "verified_files": 3,
        "missing_files": 0,
        "unexpected_files": 0,
        "checksum_mismatches": 0,
        "size_mismatches": 0,
    }
    assert report["errors"] == []
    assert report["warnings"] == [
        "verify 只校验 package 清单和 checksum；不等于 audit 或 policy 审查。"
    ]


def test_verify_agentmesh_package_reports_tampered_file(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(registry, package)

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            if info.filename == "skills/demo-skill/SKILL.md":
                target.writestr(info.filename, "# Tampered\n")
            else:
                target.writestr(info, source.read(info.filename))
    shutil.move(tampered, package)

    report = verify_agentmesh_package(package)

    assert report["valid"] is False
    assert report["summary"]["checksum_mismatches"] == 1
    assert any(error["kind"] == "checksum-mismatch" for error in report["errors"])


def test_verify_agentmesh_package_reports_missing_file(tmp_path):
    package = tmp_path / "missing-file.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "package.yaml",
            "schema: agentmesh.package/v1\nfiles:\n"
            "  - path: skills/demo-skill/SKILL.md\n"
            "    sha256: sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
            "    size: 1\n",
        )

    report = verify_agentmesh_package(package)

    assert report["valid"] is False
    assert report["summary"]["missing_files"] == 1
    assert report["errors"][0]["kind"] == "missing-file"


def test_verify_agentmesh_package_reports_unexpected_file(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(registry, package)

    expanded = tmp_path / "expanded.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(expanded, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr("extra.txt", "surprise")
    shutil.move(expanded, package)

    report = verify_agentmesh_package(package)

    assert report["valid"] is False
    assert report["summary"]["unexpected_files"] == 1
    assert any(error["kind"] == "unexpected-file" for error in report["errors"])


def test_verify_agentmesh_package_legacy_package_without_manifest_files_is_invalid(tmp_path):
    package = tmp_path / "legacy.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
        archive.writestr("skills/demo-skill/SKILL.md", "# Demo\n")

    report = verify_agentmesh_package(package)

    assert report["valid"] is False
    assert report["summary"]["declared_files"] == 0
    assert report["errors"][0]["kind"] == "missing-file-manifest"


def test_package_verify_cli_json_envelope(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(registry, package)
    runner = CliRunner()

    result = runner.invoke(app, ["package", "verify", str(package), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-verify/v1"
    assert data["command"] == "package verify"
    assert data["status"] == "ok"
    assert data["data"]["valid"] is True


def test_package_verify_cli_exits_one_for_invalid_package(tmp_path):
    package = tmp_path / "legacy.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("package.yaml", "schema: agentmesh.package/v1\n")
    runner = CliRunner()

    result = runner.invoke(app, ["package", "verify", str(package), "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-verify/v1"
    assert data["status"] == "error"
    assert data["data"]["valid"] is False


def test_package_verify_cli_human_output(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(registry, package)
    runner = CliRunner()

    result = runner.invoke(app, ["package", "verify", str(package)])

    assert result.exit_code == 0, result.output
    assert "Package verify: valid" in result.output
    assert "Declared files: 3" in result.output
    assert "Verified files: 3" in result.output


def test_verify_agentmesh_package_reports_size_mismatch(tmp_path):
    package = tmp_path / "wrong-size.zip"
    content = b"abc"
    import hashlib

    checksum = hashlib.sha256(content).hexdigest()
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "package.yaml",
            "schema: agentmesh.package/v1\nfiles:\n"
            "  - path: skills/demo-skill/SKILL.md\n"
            f"    sha256: sha256:{checksum}\n"
            "    size: 999\n",
        )
        archive.writestr("skills/demo-skill/SKILL.md", content)

    report = verify_agentmesh_package(package)

    assert report["valid"] is False
    assert report["summary"]["size_mismatches"] == 1
    assert report["errors"][0]["kind"] == "size-mismatch"


def test_verify_agentmesh_package_rejects_malformed_file_manifest_entries(tmp_path):
    package = tmp_path / "bad-files-manifest.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "package.yaml",
            "schema: agentmesh.package/v1\nfiles:\n"
            "  - path: skills/demo-skill/SKILL.md\n"
            "    sha256: nope\n"
            "    size: 1\n"
            "  - path: skills/demo-skill/OTHER.md\n"
            "    sha256: sha256:0000\n"
            "    size: -1\n"
            "  - path: package.yaml\n"
            "    sha256: sha256:0000\n"
            "    size: 1\n"
            "  - path: skills/demo-skill/SKILL.md\n"
            "    sha256: sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
            "    size: 1\n"
            "  - path: skills/demo-skill/SKILL.md\n"
            "    sha256: sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
            "    size: 1\n",
        )
        archive.writestr("skills/demo-skill/SKILL.md", "x")

    report = verify_agentmesh_package(package)

    assert report["valid"] is False
    kinds = [error["kind"] for error in report["errors"]]
    assert kinds.count("invalid-file-entry") >= 3
    assert "duplicate-file-entry" in kinds


def test_verify_agentmesh_package_reports_duplicate_zip_entry(tmp_path):
    registry = tmp_path / "agentmesh-source"
    make_registry_skill(registry, "demo-skill")
    package = tmp_path / "agentmesh-package.zip"
    export_agentmesh_package(registry, package)

    expanded = tmp_path / "expanded.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(expanded, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        duplicate = zipfile.ZipInfo("skills/demo-skill/SKILL.md")
        duplicate.date_time = (2026, 1, 1, 0, 0, 0)
        target.writestr(duplicate, "duplicate")
    shutil.move(expanded, package)

    report = verify_agentmesh_package(package)

    assert report["valid"] is False
    assert any(error["kind"] == "duplicate-zip-entry" for error in report["errors"])
