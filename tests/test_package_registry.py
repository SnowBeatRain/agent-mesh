"""测试 Package Registry：本地 skill 发布/发现/安装。

目录结构：
  ~/.agentmesh/packages/<skill-name>/<version>/
    version.yaml   — 版本元数据
    SKILL.md       — skill 入口
    agentmesh.asset.yaml
    ...
"""

from __future__ import annotations

import json

import pytest
from tests.test_package_service import make_registry_skill
from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.services.package_registry import (
    PackageRegistryError,
    install_package,
    list_available_packages,
    list_package_versions,
    publish_skill,
    uninstall_package,
)

# ── publish ──────────────────────────────────────────────────────────


def test_publish_skill_creates_version_dir_and_metadata(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")

    result = publish_skill(home, "demo-skill", "1.0.0")

    assert result["skill"] == "demo-skill"
    assert result["version"] == "1.0.0"
    version_dir = home / "packages" / "demo-skill" / "1.0.0"
    assert version_dir.is_dir()
    assert (version_dir / "SKILL.md").exists()
    assert (version_dir / "agentmesh.asset.yaml").exists()
    # version.yaml should be present
    version_meta = version_dir / "version.yaml"
    assert version_meta.exists()


def test_publish_skill_writes_correct_version_yaml(tmp_path):
    from agentmesh.utils.yaml_io import read_yaml

    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", description="My demo")

    publish_skill(home, "demo-skill", "1.0.0")

    meta = read_yaml(home / "packages" / "demo-skill" / "1.0.0" / "version.yaml")
    assert meta["name"] == "demo-skill"
    assert meta["version"] == "1.0.0"
    assert meta["description"] == "My demo"
    assert meta["schema"] == "agentmesh.package-version/v1"


def test_publish_skill_rejects_missing_skill(tmp_path):
    home = tmp_path / "agentmesh"
    (home / "skills").mkdir(parents=True)

    with pytest.raises(PackageRegistryError, match="skill 不存在"):
        publish_skill(home, "nonexistent", "1.0.0")


def test_publish_skill_rejects_duplicate_version(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")

    publish_skill(home, "demo-skill", "1.0.0")

    with pytest.raises(PackageRegistryError, match="已存在"):
        publish_skill(home, "demo-skill", "1.0.0")


def test_publish_skill_force_overwrites_existing(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# v1\n")

    publish_skill(home, "demo-skill", "1.0.0")
    # Change the skill content
    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# v2\n", encoding="utf-8")

    result = publish_skill(home, "demo-skill", "1.0.0", force=True)
    assert result["skill"] == "demo-skill"

    version_dir = home / "packages" / "demo-skill" / "1.0.0"
    assert "# v2" in (version_dir / "SKILL.md").read_text(encoding="utf-8")


def test_publish_skill_rejects_invalid_version_format(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")

    with pytest.raises(PackageRegistryError, match="版本号格式"):
        publish_skill(home, "demo-skill", "not-a-version")


def test_publish_multiple_versions(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# v1\n")
    publish_skill(home, "demo-skill", "1.0.0")

    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# v2\n", encoding="utf-8")
    publish_skill(home, "demo-skill", "2.0.0")

    versions = list_package_versions(home, "demo-skill")
    assert versions == ["1.0.0", "2.0.0"]


# ── discover / list ─────────────────────────────────────────────────


def test_list_available_packages_empty(tmp_path):
    home = tmp_path / "agentmesh"
    home.mkdir()

    packages = list_available_packages(home)
    assert packages == []


def test_list_available_packages_after_publish(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    make_registry_skill(home, "other-skill", body="# Other\n")
    publish_skill(home, "other-skill", "0.1.0")

    packages = list_available_packages(home)
    names = [p["name"] for p in packages]
    assert "demo-skill" in names
    assert "other-skill" in names


def test_list_package_versions_empty(tmp_path):
    home = tmp_path / "agentmesh"
    home.mkdir()

    versions = list_package_versions(home, "nonexistent")
    assert versions == []


def test_list_available_packages_includes_versions_and_latest(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# v1\n")
    publish_skill(home, "demo-skill", "1.0.0")
    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# v2\n", encoding="utf-8")
    publish_skill(home, "demo-skill", "2.0.0")

    packages = list_available_packages(home)
    demo = next(p for p in packages if p["name"] == "demo-skill")
    assert demo["latest"] == "2.0.0"
    assert demo["versions"] == ["1.0.0", "2.0.0"]


# ── install ─────────────────────────────────────────────────────────


def test_install_package_creates_skill_in_registry(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    # Remove from registry to simulate a clean environment
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")

    result = install_package(home, "demo-skill")

    assert result["skill"] == "demo-skill"
    assert result["version"] == "1.0.0"
    assert (home / "skills" / "demo-skill" / "SKILL.md").exists()
    assert (home / "skills" / "demo-skill" / "agentmesh.asset.yaml").exists()


def test_install_package_specific_version(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# v1\n")
    publish_skill(home, "demo-skill", "1.0.0")
    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# v2\n", encoding="utf-8")
    publish_skill(home, "demo-skill", "2.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")

    result = install_package(home, "demo-skill", version="1.0.0")

    assert result["version"] == "1.0.0"
    assert "# v1" in (home / "skills" / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_install_package_latest_picks_highest_version(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# v1\n")
    publish_skill(home, "demo-skill", "1.0.0")
    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# v2\n", encoding="utf-8")
    publish_skill(home, "demo-skill", "2.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")

    result = install_package(home, "demo-skill")

    assert result["version"] == "2.0.0"


def test_install_package_rejects_nonexistent_package(tmp_path):
    home = tmp_path / "agentmesh"
    home.mkdir()

    with pytest.raises(PackageRegistryError, match="package 不存在"):
        install_package(home, "nonexistent")


def test_install_package_rejects_nonexistent_version(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")

    with pytest.raises(PackageRegistryError, match="版本不存在"):
        install_package(home, "demo-skill", version="9.9.9")


def test_install_package_noop_when_same_content(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    # Don't remove from registry - simulate reinstall of same version

    result = install_package(home, "demo-skill")

    assert result["action"] == "skip"
    assert result["reason"] == "same-content"


def test_install_package_blocks_different_content(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# Package\n")
    publish_skill(home, "demo-skill", "1.0.0")
    # Modify registry version
    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# Modified\n", encoding="utf-8")

    with pytest.raises(PackageRegistryError, match="冲突"):
        install_package(home, "demo-skill")


def test_install_package_force_overwrites(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# Package\n")
    publish_skill(home, "demo-skill", "1.0.0")
    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# Modified\n", encoding="utf-8")

    result = install_package(home, "demo-skill", force=True)

    assert result["action"] == "installed"
    assert "# Package" in (home / "skills" / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")


# ── uninstall ───────────────────────────────────────────────────────


def test_uninstall_package_removes_from_registry(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")

    result = uninstall_package(home, "demo-skill")

    assert result["skill"] == "demo-skill"
    assert result["removed"] is True
    assert not (home / "skills" / "demo-skill").exists()


def test_uninstall_package_preserves_packages_dir(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")

    uninstall_package(home, "demo-skill")

    # The package directory should still exist
    assert (home / "packages" / "demo-skill" / "1.0.0").is_dir()


def test_uninstall_package_rejects_nonexistent(tmp_path):
    home = tmp_path / "agentmesh"
    home.mkdir()

    with pytest.raises(PackageRegistryError, match="skill 不存在"):
        uninstall_package(home, "nonexistent")


# ── dependency resolution ───────────────────────────────────────────


def test_publish_skill_captures_dependencies(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    # Add a dependency declaration
    (home / "skills" / "demo-skill" / "agentmesh.package.yaml").write_text(
        "schema: agentmesh.package-meta/v1\n"
        "dependencies:\n"
        "  - name: base-skill\n"
        '    version: ">=1.0.0"\n',
        encoding="utf-8",
    )

    publish_skill(home, "demo-skill", "1.0.0")

    from agentmesh.utils.yaml_io import read_yaml

    meta = read_yaml(home / "packages" / "demo-skill" / "1.0.0" / "version.yaml")
    assert meta["dependencies"] == [{"name": "base-skill", "version": ">=1.0.0"}]


def test_install_package_resolves_missing_dependencies(tmp_path):
    home = tmp_path / "agentmesh"
    # Setup base-skill as an available package
    make_registry_skill(home, "base-skill", body="# Base\n")
    publish_skill(home, "base-skill", "1.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "base-skill")

    # Setup demo-skill that depends on base-skill
    make_registry_skill(home, "demo-skill")
    (home / "skills" / "demo-skill" / "agentmesh.package.yaml").write_text(
        "schema: agentmesh.package-meta/v1\n"
        "dependencies:\n"
        "  - name: base-skill\n"
        '    version: ">=1.0.0"\n',
        encoding="utf-8",
    )
    publish_skill(home, "demo-skill", "1.0.0")
    shutil.rmtree(home / "skills" / "demo-skill")

    result = install_package(home, "demo-skill", resolve_deps=True)

    assert result["skill"] == "demo-skill"
    assert result["resolved_deps"] == ["base-skill"]
    # base-skill should also be installed
    assert (home / "skills" / "base-skill" / "SKILL.md").exists()


def test_install_package_fails_when_dependency_unavailable(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    (home / "skills" / "demo-skill" / "agentmesh.package.yaml").write_text(
        "schema: agentmesh.package-meta/v1\ndependencies:\n  - name: missing-dep\n",
        encoding="utf-8",
    )
    publish_skill(home, "demo-skill", "1.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")

    with pytest.raises(PackageRegistryError, match="依赖.*不可用"):
        install_package(home, "demo-skill", resolve_deps=True)


# ── CLI integration ──────────────────────────────────────────────────


def test_package_publish_cli_json(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "publish", "demo-skill", "1.0.0", "--registry", str(home), "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-publish/v1"
    assert data["status"] == "ok"
    assert data["data"]["skill"] == "demo-skill"
    assert data["data"]["version"] == "1.0.0"


def test_package_publish_cli_human_output(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "publish", "demo-skill", "1.0.0", "--registry", str(home)],
    )

    assert result.exit_code == 0, result.output
    assert "已发布" in result.output
    assert "demo-skill@1.0.0" in result.output


def test_package_publish_cli_error_envelope(tmp_path):
    home = tmp_path / "agentmesh"
    home.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "publish", "nonexistent", "1.0.0", "--registry", str(home), "--json"],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-publish/v1"
    assert data["status"] == "error"
    assert "不存在" in data["errors"][0]


def test_package_install_cli_json(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "install", "demo-skill", "--registry", str(home), "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-install/v1"
    assert data["status"] == "ok"
    assert data["data"]["skill"] == "demo-skill"
    assert data["data"]["version"] == "1.0.0"


def test_package_install_cli_human_output(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "install", "demo-skill", "--registry", str(home), "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert "已安装" in result.output
    assert "demo-skill@1.0.0" in result.output


def test_package_install_cli_specific_version(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill", body="# v1\n")
    publish_skill(home, "demo-skill", "1.0.0")
    (home / "skills" / "demo-skill" / "SKILL.md").write_text("# v2\n", encoding="utf-8")
    publish_skill(home, "demo-skill", "2.0.0")
    import shutil

    shutil.rmtree(home / "skills" / "demo-skill")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "install", "demo-skill", "1.0.0", "--registry", str(home), "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["version"] == "1.0.0"


def test_package_install_cli_error_envelope(tmp_path):
    home = tmp_path / "agentmesh"
    home.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "install", "nonexistent", "--registry", str(home), "--json"],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-install/v1"
    assert data["status"] == "error"


def test_package_uninstall_cli_json(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "uninstall", "demo-skill", "--registry", str(home), "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-uninstall/v1"
    assert data["status"] == "ok"
    assert data["data"]["removed"] is True


def test_package_list_cli_json(tmp_path):
    home = tmp_path / "agentmesh"
    make_registry_skill(home, "demo-skill")
    publish_skill(home, "demo-skill", "1.0.0")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "list", "--registry", str(home), "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema"] == "agentmesh.package-list/v1"
    assert data["data"]["total"] == 1
    assert data["data"]["packages"][0]["name"] == "demo-skill"


def test_package_list_cli_human_output_empty(tmp_path):
    home = tmp_path / "agentmesh"
    home.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["package", "list", "--registry", str(home)],
    )

    assert result.exit_code == 0, result.output
    assert "暂无已发布的 package" in result.output
