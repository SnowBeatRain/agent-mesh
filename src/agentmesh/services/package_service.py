from __future__ import annotations

import hashlib
import re
import shutil
import stat
import tempfile
import zipfile
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from agentmesh import __version__
from agentmesh.audit.engine import AuditEngine
from agentmesh.config.loader import ensure_layout, timestamp
from agentmesh.policy.service import evaluate_findings
from agentmesh.services.registry_service import list_registry_skills, skill_registry_dir
from agentmesh.utils.naming import validate_skill_name
from agentmesh.utils.yaml_io import read_yaml, write_yaml

PACKAGE_SCHEMA = "agentmesh.package/v1"
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class PackageError(RuntimeError):
    """Raised when an AgentMesh package cannot be exported or imported safely."""


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _package_file_manifest(root: Path) -> list[dict[str, str | int]]:
    files: list[dict[str, str | int]] = []
    for path in sorted((root / "skills").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        files.append(
            {"path": rel, "sha256": f"sha256:{_file_hash(path)}", "size": path.stat().st_size}
        )
    return files


def _validate_zip_name(raw_name: str) -> str | None:
    name = raw_name.replace("\\", "/")
    is_dir = name.endswith("/")
    clean = name[:-1] if is_dir else name
    if not clean:
        return None
    if clean.startswith("/") or _WINDOWS_DRIVE_RE.match(clean):
        raise PackageError(f"unsafe zip path: {raw_name}")
    parts = clean.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PackageError(f"unsafe zip path: {raw_name}")
    return clean


def _zip_info_is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK


def export_agentmesh_package(agentmesh_home: Path, out: Path) -> dict:
    if out.exists() and out.is_dir():
        raise PackageError(f"导出目标必须是 ZIP 文件路径：{out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    skills = list_registry_skills(agentmesh_home)
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "version": __version__,
        "created_at": timestamp(),
        "assets": {
            "skills": [{"name": skill.name, "path": f"skills/{skill.name}"} for skill in skills]
        },
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        package_root = Path(temp_dir) / "package"
        package_root.mkdir()
        for skill in skills:
            target = package_root / "skills" / skill.name
            for path in sorted(skill.rglob("*")):
                if path.is_symlink():
                    raise PackageError(f"不能导出 symlink 文件：{path}")
                if not path.is_file():
                    continue
                rel = path.relative_to(skill)
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        manifest["files"] = _package_file_manifest(package_root)
        write_yaml(package_root / "package.yaml", manifest)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
            package.write(package_root / "package.yaml", "package.yaml")
            for path in sorted((package_root / "skills").rglob("*")):
                if path.is_file():
                    package.write(path, path.relative_to(package_root).as_posix())
    return {
        "target": "agentmesh",
        "schema": PACKAGE_SCHEMA,
        "out": str(out),
        "package": str(out),
        "skills": [skill.name for skill in skills],
    }


def _extract_package(package_path: Path, root: Path) -> None:
    if not package_path.exists():
        raise PackageError(f"package 不存在：{package_path}")
    try:
        with zipfile.ZipFile(package_path) as package:
            for info in package.infolist():
                if _zip_info_is_symlink(info):
                    raise PackageError(f"unsafe zip path: {info.filename}")
                name = _validate_zip_name(info.filename)
                if name is None:
                    continue
                target = root / name
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
    except zipfile.BadZipFile as exc:
        raise PackageError(f"无法读取 AgentMesh package：{package_path}") from exc


def _read_package_manifest(root: Path) -> dict:
    manifest_path = root / "package.yaml"
    if not manifest_path.exists():
        raise PackageError("package 缺少 package.yaml")
    manifest = read_yaml(manifest_path)
    if manifest.get("schema") != PACKAGE_SCHEMA:
        raise PackageError("package.yaml schema 必须是 agentmesh.package/v1")
    return manifest


def _package_skill_dirs(root: Path) -> list[Path]:
    _read_package_manifest(root)
    skills_root = root / "skills"
    if not skills_root.exists():
        return []
    skills: list[Path] = []
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        try:
            name = validate_skill_name(skill_dir.name)
        except ValueError as exc:
            raise PackageError(f"package skill 目录名无效：{skill_dir.name}") from exc
        entrypoint = skill_dir / "SKILL.md"
        asset_manifest = skill_dir / "agentmesh.asset.yaml"
        if not entrypoint.exists():
            raise PackageError(f"package skill `{name}` 缺少 SKILL.md")
        if not asset_manifest.exists():
            raise PackageError(f"package skill `{name}` 缺少 agentmesh.asset.yaml")
        manifest = read_yaml(asset_manifest)
        if manifest.get("name") != name or manifest.get("kind") != "skill":
            raise PackageError(f"package skill `{name}` 的 agentmesh.asset.yaml 无效")
        skills.append(skill_dir)
    return skills


def _build_import_plan(agentmesh_home: Path, package_path: Path, root: Path) -> dict:
    skill_dirs = _package_skill_dirs(root)
    audit_root = root / "skills"
    findings = AuditEngine().audit_path(audit_root)
    policy = evaluate_findings(audit_root, findings).to_dict()
    package_hash = f"sha256:{_file_hash(package_path)}"

    items: list[dict] = []
    summary = {"skills": len(skill_dirs), "create": 0, "skip": 0, "blocked": 0, "imported": 0}
    package_allowed = bool(policy["allowed"])
    for source in skill_dirs:
        name = source.name
        target = skill_registry_dir(agentmesh_home, name)
        source_hash = _tree_hash(source)
        target_hash = _tree_hash(target) if target.exists() else None
        if target_hash is None:
            action = "create"
            reason = ""
        elif target_hash == source_hash:
            action = "skip"
            reason = "same-content"
        else:
            action = "blocked"
            reason = "same-name-different-content"
        if not package_allowed and action != "blocked":
            action = "blocked"
            reason = "audit-policy-blocked"
        summary[action] += 1
        items.append(
            {
                "name": name,
                "action": action,
                "reason": reason,
                "package_path": f"skills/{name}",
                "target_path": str(target),
                "source_hash": source_hash,
                "target_hash": target_hash,
                "source": {
                    "kind": "agentmesh-package",
                    "package_path": str(package_path),
                    "package_sha256": package_hash,
                    "imported_at": None,
                    "original_hash": source_hash,
                },
            }
        )
    allowed = package_allowed and summary["blocked"] == 0
    return {
        "schema": PACKAGE_SCHEMA,
        "package": str(package_path),
        "allowed": allowed,
        "summary": summary,
        "skills": items,
        "audit": {"findings": [finding.__dict__ for finding in findings]},
        "policy": policy,
    }


def _write_package_source_identity(target: Path, item: dict) -> None:
    manifest_path = target / "agentmesh.asset.yaml"
    manifest = read_yaml(manifest_path)
    source_identity = dict(item["source"])
    source_identity["imported_at"] = timestamp()
    manifest["source"] = source_identity
    write_yaml(manifest_path, manifest)


def _copy_skill_from_package(root: Path, item: dict) -> None:
    source = root / item["package_path"]
    target = Path(item["target_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _tree_hash(target) == item["source_hash"]:
            _write_package_source_identity(target, item)
            return
        raise PackageError(f"导入冲突：registry 中已存在同名 skill `{item['name']}`")
    shutil.copytree(source, target)
    _write_package_source_identity(target, item)


def _read_manifest_from_zip(package: zipfile.ZipFile) -> dict:
    try:
        with package.open("package.yaml") as manifest_file:
            manifest_text = manifest_file.read().decode("utf-8")
            raw_manifest = YAML(typ="safe").load(StringIO(manifest_text))
    except KeyError as exc:
        raise PackageError("package 缺少 package.yaml") from exc
    except (UnicodeDecodeError, YAMLError) as exc:
        raise PackageError("package.yaml 无效") from exc
    if raw_manifest is None:
        return {}
    if isinstance(raw_manifest, dict):
        return raw_manifest
    raise PackageError("package.yaml 无效")


def inspect_agentmesh_package(package_path: Path) -> dict:
    if not package_path.exists():
        raise PackageError(f"package 不存在：{package_path}")
    try:
        with zipfile.ZipFile(package_path) as package:
            infos = package.infolist()
            files: list[dict[str, int | str]] = []
            for info in infos:
                if _zip_info_is_symlink(info):
                    raise PackageError(f"unsafe zip path: {info.filename}")
                name = _validate_zip_name(info.filename)
                if name is None or info.is_dir():
                    continue
                files.append({"path": name, "size": info.file_size})
            manifest = _read_manifest_from_zip(package)
    except zipfile.BadZipFile as exc:
        raise PackageError(f"无法读取 AgentMesh package：{package_path}") from exc
    if manifest.get("schema") != PACKAGE_SCHEMA:
        raise PackageError("package.yaml schema 必须是 agentmesh.package/v1")
    manifest_skills = manifest.get("assets", {}).get("skills", [])
    skills = [
        {"name": item.get("name"), "path": item.get("path")}
        for item in manifest_skills
        if isinstance(item, dict)
    ]
    return {
        "schema": "agentmesh.package-inspect/v1",
        "package": str(package_path),
        "package_schema": manifest.get("schema"),
        "summary": {
            "skill_count": len(skills),
            "file_count": len(files),
            "manifest_present": True,
        },
        "manifest": {
            "schema": manifest.get("schema"),
            "version": manifest.get("version"),
            "created_at": manifest.get("created_at"),
            "skill_count": len(skills),
        },
        "skills": skills,
        "files": files,
        "warnings": ["inspect 只查看 package 内容；不等于 checksum verify、audit 或 policy 审查。"],
    }


def verify_agentmesh_package(package_path: Path) -> dict:
    if not package_path.exists():
        raise PackageError(f"package 不存在：{package_path}")
    errors: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(package_path) as package:
            actual: dict[str, dict[str, int | str]] = {}
            for info in package.infolist():
                if _zip_info_is_symlink(info):
                    raise PackageError(f"unsafe zip path: {info.filename}")
                name = _validate_zip_name(info.filename)
                if name is None or info.is_dir():
                    continue
                if name == "package.yaml":
                    continue
                content = package.read(info)
                checksum = f"sha256:{_bytes_hash(content)}"
                if name in actual:
                    errors.append({"kind": "duplicate-zip-entry", "path": name})
                    continue
                actual[name] = {
                    "sha256": checksum,
                    "size": len(content),
                }
            manifest = _read_manifest_from_zip(package)
    except zipfile.BadZipFile as exc:
        raise PackageError(f"无法读取 AgentMesh package：{package_path}") from exc
    if manifest.get("schema") != PACKAGE_SCHEMA:
        raise PackageError("package.yaml schema 必须是 agentmesh.package/v1")

    declared_files = manifest.get("files")
    if not isinstance(declared_files, list) or not declared_files:
        errors.append({"kind": "missing-file-manifest", "path": "package.yaml"})
        declared: dict[str, dict[str, int | str | None]] = {}
    else:
        declared = {}
        for item in declared_files:
            if not isinstance(item, dict):
                errors.append({"kind": "invalid-file-entry", "path": "package.yaml"})
                continue
            path = item.get("path")
            checksum = item.get("sha256")
            size = item.get("size")
            if not isinstance(path, str):
                errors.append({"kind": "invalid-file-entry", "path": "package.yaml"})
                continue
            clean_path = _validate_zip_name(path)
            if clean_path != path or path == "package.yaml":
                errors.append({"kind": "invalid-file-entry", "path": path})
                continue
            if clean_path in declared:
                errors.append({"kind": "duplicate-file-entry", "path": clean_path})
                continue
            if (
                not isinstance(checksum, str)
                or _SHA256_RE.fullmatch(checksum) is None
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
            ):
                errors.append({"kind": "invalid-file-entry", "path": clean_path})
                continue
            declared[clean_path] = {"sha256": checksum, "size": size}

    missing = sorted(set(declared) - set(actual))
    unexpected = sorted(set(actual) - set(declared))
    mismatched: list[str] = []
    size_mismatched: list[str] = []
    verified = 0
    for path, expected in declared.items():
        got = actual.get(path)
        if got is None:
            continue
        content_ok = got["sha256"] == expected["sha256"]
        size_ok = got["size"] == expected["size"]
        if not content_ok:
            mismatched.append(path)
        if not size_ok:
            size_mismatched.append(path)
        if content_ok and size_ok:
            verified += 1

    errors.extend({"kind": "missing-file", "path": path} for path in missing)
    errors.extend({"kind": "unexpected-file", "path": path} for path in unexpected)
    errors.extend({"kind": "checksum-mismatch", "path": path} for path in mismatched)
    errors.extend({"kind": "size-mismatch", "path": path} for path in size_mismatched)
    return {
        "schema": "agentmesh.package-verify/v1",
        "package": str(package_path),
        "package_schema": manifest.get("schema"),
        "valid": not errors,
        "summary": {
            "declared_files": len(declared),
            "verified_files": verified,
            "missing_files": len(missing),
            "unexpected_files": len(unexpected),
            "checksum_mismatches": len(mismatched),
            "size_mismatches": len(size_mismatched),
        },
        "errors": errors,
        "warnings": ["verify 只校验 package 清单和 checksum；不等于 audit 或 policy 审查。"],
    }


def import_agentmesh_package(agentmesh_home: Path, package_path: Path, *, apply: bool) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _extract_package(package_path, root)
        plan = _build_import_plan(agentmesh_home, package_path, root)
        if not apply:
            return plan
        if not plan["allowed"]:
            raise PackageError("package import blocked; run --dry-run to inspect audit/conflicts")
        ensure_layout(agentmesh_home)
        imported = 0
        for item in plan["skills"]:
            if item["action"] not in {"create", "skip"}:
                continue
            _copy_skill_from_package(root, item)
            if item["action"] == "create":
                imported += 1
        plan["summary"]["imported"] = imported
        return plan
