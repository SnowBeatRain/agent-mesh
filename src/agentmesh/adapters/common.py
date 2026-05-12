from collections.abc import Iterable
from pathlib import Path

from agentmesh.models.skill import NativeSkill
from agentmesh.utils.frontmatter import FrontmatterError, read_skill_document
from agentmesh.utils.hashing import hash_file
from agentmesh.utils.naming import validate_skill_name


def _build_native_skill(
    agent: str,
    entrypoint: Path,
    source: Path,
    *,
    skip_system: bool,
    fallback_name: str | None = None,
) -> NativeSkill | None:
    """Read a single skill entrypoint (SKILL.md / .md / .mdc) and build a
    NativeSkill with frontmatter-sourced metadata when present.

    Returns None if the name cannot be validated even from the filesystem
    fallback, so callers can simply ``extend`` the result without None checks.
    """
    warnings: list[str] = []
    try:
        doc = read_skill_document(entrypoint)
    except FrontmatterError as exc:
        doc = None
        warnings.append(str(exc))
    raw_name = doc.metadata.get("name") if doc else None
    raw_name = raw_name or fallback_name or source.name
    try:
        name = validate_skill_name(str(raw_name))
    except ValueError:
        return None
    description = str(doc.metadata.get("description") or "") if doc else ""
    return NativeSkill(
        name=name,
        description=description,
        agent=agent,
        source_path=source,
        entrypoint=entrypoint,
        digest=hash_file(entrypoint),
        system=".system" in source.parts,
        warnings=tuple(warnings),
    )


def scan_flat_skill_files(
    agent: str,
    root: Path,
    *,
    suffixes: Iterable[str] = (".md", ".mdc"),
    skip_names: Iterable[str] = (),
) -> list[NativeSkill]:
    """Scan a flat directory of skill files (cursor/.cursor/rules, windsurf/.windsurf/rules).

    Unlike ``scan_skill_dirs`` which expects each skill to live in its own
    subdirectory with a SKILL.md inside, runtimes like Cursor and Windsurf
    store each rule as a single file at the top level. This helper parses the
    same YAML frontmatter convention so description / custom name / warnings
    are surfaced the same way, and falls back to the file stem when a file
    has no frontmatter at all.
    """
    if not root.exists():
        return []
    skills: list[NativeSkill] = []
    skip = set(skip_names)
    for entrypoint in sorted(root.iterdir()):
        if not entrypoint.is_file():
            continue
        if entrypoint.suffix not in suffixes:
            continue
        if entrypoint.name in skip:
            continue
        skill = _build_native_skill(
            agent,
            entrypoint,
            entrypoint.parent,
            skip_system=False,
            fallback_name=entrypoint.stem,
        )
        if skill is not None:
            skills.append(skill)
    return skills


def scan_single_skill_file(
    agent: str,
    entrypoint: Path,
    *,
    fallback_name: str,
) -> list[NativeSkill]:
    """Wrap a single legacy single-file skill (.cursorrules, .windsurfrules,
    .aider.conventions.md) as a NativeSkill, parsing frontmatter when present.
    """
    if not entrypoint.exists() or not entrypoint.is_file():
        return []
    skill = _build_native_skill(
        agent,
        entrypoint,
        entrypoint.parent,
        skip_system=False,
        fallback_name=fallback_name,
    )
    return [skill] if skill is not None else []


def scan_skill_dirs(agent: str, root: Path, skip_system: bool = True) -> list[NativeSkill]:
    if not root.exists():
        return []
    skills: list[NativeSkill] = []
    for entrypoint in sorted(root.glob("**/SKILL.md")):
        source = entrypoint.parent
        if skip_system and ".system" in source.parts:
            continue
        warnings: list[str] = []
        try:
            doc = read_skill_document(entrypoint)
        except FrontmatterError as exc:
            doc = None
            warnings.append(str(exc))
        raw_name = doc.metadata.get("name") if doc else None
        raw_name = raw_name or source.name
        try:
            name = validate_skill_name(str(raw_name))
        except ValueError:
            continue
        description = str(doc.metadata.get("description") or "") if doc else ""
        skills.append(
            NativeSkill(
                name=name,
                description=description,
                agent=agent,
                source_path=source,
                entrypoint=entrypoint,
                digest=hash_file(entrypoint),
                system=".system" in source.parts,
                warnings=tuple(warnings),
            )
        )
    return skills
