"""Package Registry：本地 skill 发布/发现/安装。

目录结构：
  ~/.agentmesh/packages/<skill-name>/<version>/
    version.yaml        — 版本元数据
    SKILL.md            — skill 入口
    agentmesh.asset.yaml
    agentmesh.skill.yaml
    agentmesh.package.yaml  （可选，依赖声明）
    ...
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from agentmesh.config.loader import ensure_layout, registry_skills_root
from agentmesh.utils.naming import validate_skill_name
from agentmesh.utils.yaml_io import read_yaml, write_yaml

PACKAGE_VERSION_SCHEMA = "agentmesh.package-version/v1"
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")
_AGENTMESH_ASSET_FILES = {"SKILL.md", "agentmesh.asset.yaml", "agentmesh.skill.yaml"}


class PackageRegistryError(RuntimeError):
    """Package registry 操作失败时抛出。"""


def _packages_root(agentmesh_home: Path) -> Path:
    return agentmesh_home / "packages"


def _skill_package_dir(agentmesh_home: Path, name: str) -> Path:
    return _packages_root(agentmesh_home) / name


def _validate_version(version: str) -> str:
    if _SEMVER_RE.fullmatch(version) is None:
        raise PackageRegistryError(f"版本号格式无效：{version}（需 semver 格式，如 1.0.0）")
    return version


def _resolve_version_dir(agentmesh_home: Path, name: str, version: str | None) -> tuple[Path, str]:
    """解析版本目录，返回 (version_dir, resolved_version)。"""
    pkg_dir = _skill_package_dir(agentmesh_home, name)
    if not pkg_dir.is_dir():
        raise PackageRegistryError(f"package 不存在：{name}")

    if version is not None:
        _validate_version(version)
        v_dir = pkg_dir / version
        if not v_dir.is_dir():
            raise PackageRegistryError(f"版本不存在：{name}@{version}")
        return v_dir, version

    # 没指定版本，取最新
    versions = _sorted_versions(pkg_dir)
    if not versions:
        raise PackageRegistryError(f"package 没有可用版本：{name}")
    latest = versions[-1]
    return pkg_dir / latest, latest


def _sorted_versions(pkg_dir: Path) -> list[str]:
    """返回按 semver 排序的版本号列表。"""
    versions: list[str] = []
    if not pkg_dir.is_dir():
        return versions
    for child in sorted(pkg_dir.iterdir()):
        if child.is_dir() and (child / "version.yaml").exists():
            versions.append(child.name)
    return sorted(versions, key=_version_sort_key)


def _version_sort_key(v: str) -> tuple[int, ...]:
    """将 semver 转换为可排序的元组。"""
    core = v.split("-")[0]
    return tuple(int(p) for p in core.split("."))


_EXCLUDE_FROM_HASH = {"version.yaml"}


def _tree_hash(root: Path, *, exclude: set[str] | None = None) -> str:
    import hashlib

    exclude = exclude or set()
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if path.name in exclude or rel in exclude:
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


# ── publish ──────────────────────────────────────────────────────────


def publish_skill(
    agentmesh_home: Path,
    skill_name: str,
    version: str,
    *,
    force: bool = False,
) -> dict:
    """将 registry 中的 skill 发布到本地 package 目录。"""
    try:
        validate_skill_name(skill_name)
    except ValueError as exc:
        raise PackageRegistryError(f"skill 名称无效：{skill_name}") from exc

    _validate_version(version)

    src = registry_skills_root(agentmesh_home) / skill_name
    if not src.is_dir():
        raise PackageRegistryError(f"skill 不存在：{skill_name}")

    dest = _skill_package_dir(agentmesh_home, skill_name) / version
    if dest.is_dir() and not force:
        raise PackageRegistryError(f"版本已存在：{skill_name}@{version}；使用 force=True 覆盖")

    if dest.is_dir() and force:
        shutil.rmtree(dest)

    # Copy skill files
    shutil.copytree(src, dest)

    # Read metadata from skill
    asset_path = src / "agentmesh.asset.yaml"
    asset_yaml = read_yaml(asset_path) if asset_path.exists() else {}
    description = str(asset_yaml.get("description", ""))

    # Read dependencies if package.yaml exists
    dependencies: list[dict] = []
    pkg_meta_path = src / "agentmesh.package.yaml"
    if pkg_meta_path.exists():
        pkg_meta = read_yaml(pkg_meta_path)
        dependencies = pkg_meta.get("dependencies", [])

    # Write version.yaml
    version_meta: dict = {
        "schema": PACKAGE_VERSION_SCHEMA,
        "name": skill_name,
        "version": version,
        "description": description,
        "published_at": _timestamp(),
    }
    if dependencies:
        version_meta["dependencies"] = dependencies
    write_yaml(dest / "version.yaml", version_meta)

    ensure_layout(agentmesh_home)

    return {
        "skill": skill_name,
        "version": version,
        "path": str(dest),
    }


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


# ── discover ─────────────────────────────────────────────────────────


def list_available_packages(agentmesh_home: Path) -> list[dict]:
    """列出所有已发布的 package。"""
    root = _packages_root(agentmesh_home)
    if not root.is_dir():
        return []

    packages: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        versions = _sorted_versions(child)
        if not versions:
            continue
        latest = versions[-1]
        meta = read_yaml(child / latest / "version.yaml")
        packages.append(
            {
                "name": child.name,
                "latest": latest,
                "versions": versions,
                "description": meta.get("description", ""),
            }
        )
    return packages


def list_package_versions(agentmesh_home: Path, skill_name: str) -> list[str]:
    """列出某个 package 的所有版本。"""
    pkg_dir = _skill_package_dir(agentmesh_home, skill_name)
    return _sorted_versions(pkg_dir)


# ── install ──────────────────────────────────────────────────────────


def install_package(
    agentmesh_home: Path,
    skill_name: str,
    *,
    version: str | None = None,
    resolve_deps: bool = False,
    force: bool = False,
) -> dict:
    """从本地 package 目录安装 skill 到 registry。"""
    version_dir, resolved_version = _resolve_version_dir(agentmesh_home, skill_name, version)

    # Resolve dependencies first
    resolved_deps: list[str] = []
    if resolve_deps:
        version_meta = read_yaml(version_dir / "version.yaml")
        dependencies = version_meta.get("dependencies", [])
        for dep in dependencies:
            dep_name = dep["name"]
            dep_version = dep.get("version")  # Could be constraint like ">=1.0.0"
            # Check if dependency is already installed in registry
            dep_registry_dir = registry_skills_root(agentmesh_home) / dep_name
            if dep_registry_dir.exists():
                resolved_deps.append(dep_name)
                continue
            # Try to install from packages
            try:
                dep_resolved = _resolve_version_from_constraint(
                    agentmesh_home, dep_name, dep_version
                )
                install_package(agentmesh_home, dep_name, version=dep_resolved)
                resolved_deps.append(dep_name)
            except PackageRegistryError as exc:
                raise PackageRegistryError(
                    f"依赖不可用：{dep_name}（{skill_name} 需要此依赖）"
                ) from exc

    # Check for conflicts
    target = registry_skills_root(agentmesh_home) / skill_name
    if target.exists():
        source_hash = _tree_hash(version_dir, exclude=_EXCLUDE_FROM_HASH)
        target_hash = _tree_hash(target)
        if source_hash == target_hash:
            return {
                "skill": skill_name,
                "version": resolved_version,
                "action": "skip",
                "reason": "same-content",
                "resolved_deps": resolved_deps,
            }
        if not force:
            raise PackageRegistryError(
                f"冲突：registry 中已存在同名 skill `{skill_name}`，内容不同；使用 force=True 覆盖"
            )
        # Force overwrite
        shutil.rmtree(target)

    # Install
    ensure_layout(agentmesh_home)
    shutil.copytree(version_dir, target)
    # Remove version.yaml from registry copy (it's metadata for the package, not the skill)
    version_yaml_in_target = target / "version.yaml"
    if version_yaml_in_target.exists():
        version_yaml_in_target.unlink()

    return {
        "skill": skill_name,
        "version": resolved_version,
        "action": "installed",
        "resolved_deps": resolved_deps,
    }


def _resolve_version_from_constraint(
    agentmesh_home: Path, name: str, constraint: str | None
) -> str | None:
    """从版本约束中解析出要安装的版本号。

    MVP 实现：只支持精确版本和无约束（取最新）。
    """
    if constraint is None:
        # No constraint - pick latest
        return None

    # Parse ">=x.y.z" style
    if constraint.startswith(">="):
        return None  # Pick latest (satisfies >= constraint)

    # Exact version
    _validate_version(constraint)
    return constraint


# ── uninstall ────────────────────────────────────────────────────────


def uninstall_package(agentmesh_home: Path, skill_name: str) -> dict:
    """从 registry 中移除 skill（不删除 package 目录）。"""
    target = registry_skills_root(agentmesh_home) / skill_name
    if not target.is_dir():
        raise PackageRegistryError(f"skill 不存在：{skill_name}")

    shutil.rmtree(target)
    return {
        "skill": skill_name,
        "removed": True,
    }
