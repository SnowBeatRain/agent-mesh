import json
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2, rmtree

from agentmesh.audit.engine import AuditEngine
from agentmesh.config.loader import (
    AGENT_TARGETS,
    legacy_registry_skills_root,
    registry_skills_root,
)
from agentmesh.models.manifest import AssetManifest, SkillManifest
from agentmesh.models.skill import NativeSkill
from agentmesh.utils.yaml_io import read_yaml, write_yaml

EXCLUDED_IMPORT_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}
EXCLUDED_IMPORT_FILES = {
    ".DS_Store",
    "Thumbs.db",
}


class RegistryImportConflict(RuntimeError):
    """Raised when an import would overwrite a different registry skill."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def skill_registry_dir(agentmesh_home: Path, name: str) -> Path:
    return registry_skills_root(agentmesh_home) / name


def legacy_skill_registry_dir(agentmesh_home: Path, name: str) -> Path:
    return legacy_registry_skills_root(agentmesh_home) / name


def resolve_skill_registry_dir(agentmesh_home: Path, name: str) -> Path:
    current = skill_registry_dir(agentmesh_home, name)
    if current.exists():
        return current
    legacy = legacy_skill_registry_dir(agentmesh_home, name)
    return legacy if legacy.exists() else current


def _is_excluded(rel: Path) -> bool:
    return (
        any(part in EXCLUDED_IMPORT_DIRS for part in rel.parts) or rel.name in EXCLUDED_IMPORT_FILES
    )


def _copy_filtered_tree(source: Path, target: Path) -> list[str]:
    excluded: list[str] = []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if _is_excluded(rel):
            excluded.append(rel.as_posix() + ("/" if path.is_dir() else ""))
            continue
        dest = target / rel
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            copy2(path, dest)
    return excluded


def _read_existing_source_hash(target: Path) -> str | None:
    provenance = target / "provenance.yaml"
    if not provenance.exists():
        return None
    return read_yaml(provenance).get("hash")


def import_skill(agentmesh_home: Path, skill: NativeSkill, *, dry_run: bool = False) -> Path | dict:
    target = skill_registry_dir(agentmesh_home, skill.name)
    if dry_run:
        preview: dict[str, object] = {
            "skill": skill.name,
            "source": str(skill.source_path),
            "target": str(target),
            "digest": skill.digest,
            "would_write": not target.exists()
            or _read_existing_source_hash(target) != skill.digest,
            "existing_hash": _read_existing_source_hash(target),
            "conflict": bool(
                target.exists()
                and _read_existing_source_hash(target)
                and _read_existing_source_hash(target) != skill.digest
            ),
        }
        return preview
    # Preserve imported_at across idempotent re-imports. Only bump the timestamp
    # when the source digest has changed (or the skill is new).
    preserved_imported_at: str | None = None
    if target.exists():
        existing_hash = _read_existing_source_hash(target)
        if existing_hash and existing_hash != skill.digest:
            raise RegistryImportConflict(
                f"导入冲突：registry 中已存在同名 skill `{skill.name}`，"
                "且内容与当前来源不同；请先使用 diff/conflicts 检查后再手动处理。"
            )
        if existing_hash == skill.digest:
            existing_provenance = _safe_read_yaml(target / "provenance.yaml")
            existing_imported_at = existing_provenance.get("imported_at")
            if isinstance(existing_imported_at, str) and existing_imported_at:
                preserved_imported_at = existing_imported_at
        # 保持幂等：先清理可生成内容，但不追踪 secrets；MVP 只处理测试 fixture 和普通 skill 文档。
        for child in target.iterdir():
            if child.is_dir():
                rmtree(child)
            else:
                child.unlink()
    target.mkdir(parents=True, exist_ok=True)
    excluded = _copy_filtered_tree(skill.source_path, target)
    asset = AssetManifest(name=skill.name, description=skill.description)
    skill_manifest = SkillManifest(name=skill.name, description=skill.description)
    write_yaml(target / "agentmesh.asset.yaml", asset.model_dump(mode="json", by_alias=True))
    write_yaml(
        target / "agentmesh.skill.yaml", skill_manifest.model_dump(mode="json", by_alias=True)
    )
    write_yaml(
        target / "provenance.yaml",
        {
            "source_agent": skill.agent,
            "source_path": str(skill.source_path),
            "hash": skill.digest,
            "excluded_count": len(excluded),
            "excluded_paths": excluded,
            "imported_at": preserved_imported_at or _now_iso(),
        },
    )
    return target


def list_registry_skills(agentmesh_home: Path) -> list[Path]:
    roots = [registry_skills_root(agentmesh_home), legacy_registry_skills_root(agentmesh_home)]
    skills: dict[str, Path] = {}
    for root in roots:
        if root.exists():
            for path in sorted(p for p in root.iterdir() if p.is_dir()):
                skills.setdefault(path.name, path)
    return [skills[name] for name in sorted(skills)]


def reindex_registry_skills(agentmesh_home: Path) -> dict:
    skills = []
    for skill_dir in list_registry_skills(agentmesh_home):
        asset = _safe_read_yaml(skill_dir / "agentmesh.asset.yaml")
        skill_manifest = _safe_read_yaml(skill_dir / "agentmesh.skill.yaml")
        files = sorted(
            path.relative_to(skill_dir).as_posix()
            for path in skill_dir.rglob("*")
            if path.is_file()
        )
        description = str(
            asset.get("description")
            or skill_manifest.get("description")
            or read_manifest_description(skill_dir)
        )
        skills.append(
            {
                "name": skill_dir.name,
                "description": description,
                "path": str(skill_dir),
                "asset": asset,
                "skill_manifest": skill_manifest,
                "files": files,
            }
        )
    index = {
        "schema": "agentmesh.registry-skills-index/v1",
        "summary": {"skills": len(skills)},
        "skills": skills,
    }
    index_path = agentmesh_home / "registry" / "index" / "skills.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index


def read_manifest_description(skill_dir: Path) -> str:
    manifest = skill_dir / "agentmesh.asset.yaml"
    if not manifest.exists():
        return ""
    return read_yaml(manifest).get("description", "")


def find_duplicate_candidates(agentmesh_home: Path) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for skill_dir in list_registry_skills(agentmesh_home):
        description = read_manifest_description(skill_dir)
        if description:
            groups.setdefault(description, []).append(skill_dir.name)
    return {key: names for key, names in groups.items() if len(names) > 1}


SENSITIVE_PROVENANCE_KEYS = {"token", "api_key", "apikey", "password", "secret", "credential"}


def _redact_mapping(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in SENSITIVE_PROVENANCE_KEYS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_mapping(item)
        return redacted
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value


def _safe_read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    value = read_yaml(path)
    return value if isinstance(value, dict) else {}


def describe_registry_skill(agentmesh_home: Path, name: str) -> dict:
    skill_dir = resolve_skill_registry_dir(agentmesh_home, name)
    if not skill_dir.exists():
        raise FileNotFoundError(f"skill not found: {name}")

    asset = _safe_read_yaml(skill_dir / "agentmesh.asset.yaml")
    skill_manifest = _safe_read_yaml(skill_dir / "agentmesh.skill.yaml")
    provenance = _redact_mapping(_safe_read_yaml(skill_dir / "provenance.yaml"))
    files = sorted(
        path.relative_to(skill_dir).as_posix() for path in skill_dir.rglob("*") if path.is_file()
    )
    findings = AuditEngine().audit_path(skill_dir)
    secret_count = sum(1 for finding in findings if finding.kind == "secret")
    script_count = sum(1 for finding in findings if finding.kind == "dangerous-script")
    description = str(
        asset.get("description")
        or skill_manifest.get("description")
        or read_manifest_description(skill_dir)
    )
    return {
        "skill": {
            "name": name,
            "description": description,
            "path": str(skill_dir),
            "asset_schema": asset.get("schema"),
            "skill_schema": skill_manifest.get("schema"),
            "files": {"total": len(files), "paths": files},
        },
        "provenance": provenance,
        "risk_summary": {
            "findings": len(findings),
            "secrets": secret_count,
            "scripts": script_count,
        },
    }


def _directory_total_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def _skill_imported_at(skill_dir: Path, provenance: dict) -> str | None:
    """Return an ISO-8601 timestamp for when the skill entered the registry.

    Prefers ``provenance.imported_at`` when present (newly-imported skills).
    Falls back to the provenance.yaml mtime for legacy skills, and finally to
    the skill directory mtime.
    """
    provenance_imported_at = provenance.get("imported_at") if isinstance(provenance, dict) else None
    if provenance_imported_at:
        return str(provenance_imported_at)

    prov_path = skill_dir / "provenance.yaml"
    source = prov_path if prov_path.exists() else skill_dir
    try:
        ts = source.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def describe_registry_skill_detailed(
    agentmesh_home: Path,
    name: str,
    *,
    with_diff_targets: list[str] | None = None,
) -> dict:
    """Return a rich description of a single registry skill.

    Extends :func:`describe_registry_skill` with fields needed by the UI and
    `skills list --detailed`:

    - ``file_count`` / ``total_bytes``
    - ``imported_at`` (ISO-8601, falls back to mtime for legacy skills)
    - ``source_agent`` (from provenance)
    - ``enabled_targets`` (targets currently enabled in state matrix)
    - ``last_diff`` (per-target conflict level name, optional)

    The ``with_diff_targets`` parameter is optional. When ``None``, diff is not
    computed (cheap listing). When a list is given, each target's diff level
    is computed and returned as ``last_diff[target]``.
    """
    # Lazy imports to avoid circular references between services.
    from agentmesh.engine.diff_engine import diff_skill
    from agentmesh.services.skill_state_service import load_skills_state

    base = describe_registry_skill(agentmesh_home, name)
    skill_dir = resolve_skill_registry_dir(agentmesh_home, name)

    provenance = base.get("provenance") or {}
    source_agent = provenance.get("source_agent") if isinstance(provenance, dict) else None

    state = load_skills_state(agentmesh_home)
    skills_state = state.get("skills") or {}
    entry = skills_state.get(name) or {}
    targets = entry.get("targets") if isinstance(entry, dict) else {}
    enabled_targets = sorted(
        target
        for target, cfg in (targets or {}).items()
        if isinstance(cfg, dict) and cfg.get("enabled") is True
    )

    last_diff: dict[str, str] = {}
    if with_diff_targets:
        for target in with_diff_targets:
            try:
                result = diff_skill(agentmesh_home, name, target)
            except ValueError:
                # Unknown target (not in AGENT_TARGETS) — skip gracefully.
                continue
            last_diff[target] = result.name

    provenance_dict = provenance if isinstance(provenance, dict) else {}
    detailed: dict = dict(base)
    detailed["skill"] = {
        **base["skill"],
        "file_count": base["skill"]["files"]["total"],
        "total_bytes": _directory_total_bytes(skill_dir),
        "imported_at": _skill_imported_at(skill_dir, provenance_dict),
        "source_agent": source_agent,
    }
    detailed["enabled_targets"] = enabled_targets
    detailed["last_diff"] = last_diff
    return detailed


def list_registry_skills_detailed(
    agentmesh_home: Path,
    *,
    with_diff_targets: list[str] | None = None,
) -> list[dict]:
    """Return detailed descriptions for every skill in the registry.

    Each item is the result of :func:`describe_registry_skill_detailed` for
    one skill. The list is sorted by skill name (same order as
    :func:`list_registry_skills`).
    """
    items: list[dict] = []
    for skill_dir in list_registry_skills(agentmesh_home):
        try:
            detail = describe_registry_skill_detailed(
                agentmesh_home, skill_dir.name, with_diff_targets=with_diff_targets
            )
        except FileNotFoundError:
            continue
        items.append(detail)
    return items



class RegistrySkillNotFound(FileNotFoundError):
    """Raised when a rename/delete target does not exist in the registry."""


class RegistrySkillExists(RuntimeError):
    """Raised when a rename would overwrite an existing registry skill."""


def rename_registry_skill(
    agentmesh_home: Path,
    old_name: str,
    new_name: str,
) -> Path:
    """Rename a registry skill directory and rewrite in-skill metadata.

    Updates ``agentmesh.asset.yaml`` and ``agentmesh.skill.yaml`` name fields
    so subsequent scans / exports / diff see the new canonical name. Callers
    are responsible for also calling :func:`rename_skill_state` to keep
    ``state/skills.yaml`` in sync.

    Raises :class:`RegistrySkillNotFound` when ``old_name`` is not in the
    registry, and :class:`RegistrySkillExists` when ``new_name`` already
    points at a different skill directory.
    """
    from agentmesh.utils.naming import validate_skill_name

    validate_skill_name(new_name)
    source = skill_registry_dir(agentmesh_home, old_name)
    legacy_source = legacy_skill_registry_dir(agentmesh_home, old_name)
    resolved = source if source.exists() else (legacy_source if legacy_source.exists() else None)
    if resolved is None:
        raise RegistrySkillNotFound(f"registry 中不存在 skill：{old_name}")
    if new_name == old_name:
        return resolved
    target = skill_registry_dir(agentmesh_home, new_name)
    if target.exists():
        raise RegistrySkillExists(
            f"registry 中已存在 skill：{new_name}；请先删除或改用其他名字"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved.rename(target)
    # Rewrite name fields inside manifest files so downstream consumers see
    # the new canonical name. Leave digest/hash fields alone — they hash
    # file bytes, not the manifest name.
    for manifest_name in ("agentmesh.asset.yaml", "agentmesh.skill.yaml"):
        manifest_path = target / manifest_name
        if not manifest_path.exists():
            continue
        data = _safe_read_yaml(manifest_path)
        data["name"] = new_name
        write_yaml(manifest_path, data)
    return target


def delete_registry_skill(agentmesh_home: Path, name: str) -> Path:
    """Delete a registry skill directory. Does not touch sync state or
    target-side copies; callers that want cascading cleanup should invoke
    :func:`purge_target_skill_copies` separately.
    """
    source = skill_registry_dir(agentmesh_home, name)
    legacy = legacy_skill_registry_dir(agentmesh_home, name)
    resolved = source if source.exists() else (legacy if legacy.exists() else None)
    if resolved is None:
        raise RegistrySkillNotFound(f"registry 中不存在 skill：{name}")
    rmtree(resolved)
    return resolved


def purge_target_skill_copies(
    agentmesh_home: Path,
    name: str,
    *,
    home: Path | None = None,
) -> list[dict[str, str]]:
    """Remove AgentMesh-managed copies of ``name`` from every known target.

    Only directories that carry an AgentMesh lockfile
    (``.agentmesh-lock.yaml`` or ``.<name>.agentmesh-link.yaml``) are
    removed — this guards against nuking a user's own hand-rolled skill
    that happens to share the same name.

    Returns a list of ``{"target", "path", "action"}`` records describing
    what was touched, so callers can surface the outcome in CLI output.
    """
    from agentmesh.config import loader as _loader
    from agentmesh.engine.diff_engine import target_skill_path
    from agentmesh.services.sync_service import LOCK_FILE, _link_lock_path

    base = home or _loader.user_home()
    results: list[dict[str, str]] = []
    for target in sorted(AGENT_TARGETS):
        try:
            path = target_skill_path(name, target, base)
        except ValueError:
            continue
        if path.is_symlink():
            # Only remove symlinks that we previously wrote (have a link-lock).
            link_lock = _link_lock_path(path)
            if link_lock.exists():
                path.unlink()
                link_lock.unlink()
                results.append(
                    {"target": target, "path": str(path), "action": "removed_symlink"}
                )
            else:
                results.append(
                    {"target": target, "path": str(path), "action": "skipped_unmanaged_symlink"}
                )
            continue
        if not path.exists():
            continue
        lock = path / LOCK_FILE
        if lock.exists():
            rmtree(path)
            results.append({"target": target, "path": str(path), "action": "removed_directory"})
        else:
            results.append(
                {"target": target, "path": str(path), "action": "skipped_unmanaged_directory"}
            )
    return results
