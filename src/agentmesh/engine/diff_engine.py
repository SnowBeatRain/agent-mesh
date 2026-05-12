from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from agentmesh.audit.engine import AuditEngine
from agentmesh.config import loader
from agentmesh.config.loader import AGENT_TARGETS
from agentmesh.engine.conflict_resolver import ConflictLevel, ConflictResult
from agentmesh.services.registry_service import resolve_skill_registry_dir

METADATA_FILES = {"agentmesh.asset.yaml", "agentmesh.skill.yaml", "provenance.yaml"}
LOCK_FILES = {".agentmesh-lock.yaml"}


def target_skill_path(name: str, target: str, home: Path | None = None) -> Path:
    if target not in AGENT_TARGETS:
        raise ValueError(f"暂不支持目标 agent：{target}")
    base = home or loader.user_home()
    return base.joinpath(*AGENT_TARGETS[target], name)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(_semantic_bytes(path))
    return digest.hexdigest()


def _semantic_bytes(path: Path) -> bytes:
    if path.name != "SKILL.md":
        return path.read_bytes()
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) == 3:
            return parts[2].encode("utf-8")
    return text.encode("utf-8")


def _file_map(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    result: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel in LOCK_FILES:
            continue
        result[rel] = _hash_file(path)
    return result


def _change_kind(path: str) -> str:
    if path in METADATA_FILES:
        return "metadata"
    if path == "SKILL.md":
        return "entrypoint"
    return "file-tree"


def _build_changes(source_files: dict[str, str], target_files: dict[str, str]) -> list[dict]:
    changes: list[dict] = []
    for path in sorted(set(source_files) | set(target_files)):
        source_hash = source_files.get(path)
        target_hash = target_files.get(path)
        if source_hash == target_hash:
            continue
        if source_hash is None:
            status = "target-only"
        elif target_hash is None:
            status = "source-only"
        else:
            status = "changed"
        changes.append({"path": path, "status": status, "kind": _change_kind(path)})
    return changes


def diff_skill(
    agentmesh_home: Path, name: str, target: str, home: Path | None = None
) -> ConflictResult:
    source = resolve_skill_registry_dir(agentmesh_home, name)
    target_path = target_skill_path(name, target, home)
    if not target_path.exists():
        return ConflictResult(
            ConflictLevel.STRUCTURE_CHANGED,
            "STRUCTURE_CHANGED",
            "目标 skill 不存在",
            [{"path": ".", "status": "missing-target", "kind": "structure"}],
        )
    if target_path.is_symlink() and target_path.resolve() == source.resolve():
        return ConflictResult(ConflictLevel.IDENTICAL, "IDENTICAL", "内容一致", [])

    findings = AuditEngine().audit_path(source)
    if any(finding.severity == "block" for finding in findings):
        return ConflictResult(
            ConflictLevel.SECURITY_BLOCK,
            "SECURITY_BLOCK",
            "发现安全风险：<redacted>",
            [
                {"path": finding.path, "status": "blocked", "kind": finding.kind}
                for finding in findings
            ],
        )

    source_files = _file_map(source)
    target_files = _file_map(target_path)
    changes = _build_changes(source_files, target_files)
    if not changes:
        return ConflictResult(ConflictLevel.IDENTICAL, "IDENTICAL", "内容一致", [])

    kinds = {change["kind"] for change in changes}
    if kinds <= {"metadata"}:
        return ConflictResult(ConflictLevel.METADATA_ONLY, "METADATA_ONLY", "仅元数据不同", changes)
    if "file-tree" in kinds:
        return ConflictResult(
            ConflictLevel.MANUAL_REVIEW, "MANUAL_REVIEW", "文件树变化需人工确认", changes
        )
    return ConflictResult(ConflictLevel.CONTENT_CHANGED, "CONTENT_CHANGED", "内容不同", changes)


# ─────────────────────────────────────────────────────────────────────────
# Phase A5: structured per-file / per-line diff for UI consumption.
# ─────────────────────────────────────────────────────────────────────────


# A single file in the source or target looks text-like if decoding as UTF-8 does
# not produce surrogate / control-heavy output. We keep this heuristic conservative
# so binary blobs never leak into JSON responses.
_TEXT_EXTENSIONS = {
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".py",
    ".sh",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".toml",
    ".cfg",
    ".ini",
    ".xml",
    ".rst",
    ".conf",
    ".mdc",
    ".mdx",
    ".env",
    ".gitignore",
    ".dockerignore",
}


def _is_text_file(path: Path) -> bool:
    """Best-effort binary detection used only for diff rendering.

    Returns ``True`` when the file is safe to decode as UTF-8 and render as a
    unified diff. Unknown extensions fall back to a UTF-8 decode probe that
    reads at most 8 KiB.
    """
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        return True
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _read_text_lines(path: Path) -> list[str] | None:
    """Return the file contents as a list of lines, or ``None`` if binary."""
    if not path.is_file():
        return None
    if not _is_text_file(path):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    return text.splitlines(keepends=False)


def _strip_skill_frontmatter(lines: list[str]) -> list[str]:
    """Drop the leading YAML frontmatter of ``SKILL.md`` so diffs focus on body.

    Mirrors the semantic hashing in :func:`_semantic_bytes`.
    """
    if lines and lines[0] == "---":
        for i in range(1, len(lines)):
            if lines[i] == "---":
                return lines[i + 1 :]
    return lines


def _semantic_text_lines(path: Path, rel_path: str) -> list[str] | None:
    lines = _read_text_lines(path)
    if lines is None:
        return None
    if rel_path == "SKILL.md":
        return _strip_skill_frontmatter(lines)
    return lines


def _unified_hunks(
    source_lines: list[str],
    target_lines: list[str],
    *,
    context: int = 3,
) -> list[dict]:
    """Return a list of hunk dicts compatible with the UI.

    Each hunk looks like::

        {
            "source_start": 1, "source_length": 4,
            "target_start": 1, "target_length": 6,
            "lines": [
                {"type": "context", "text": "..."},
                {"type": "delete",  "text": "-old"},
                {"type": "insert",  "text": "+new"},
            ],
        }

    We build it ourselves (instead of parsing ``difflib.unified_diff`` output)
    to keep the type labels structured for front-end rendering.
    """
    matcher = difflib.SequenceMatcher(a=source_lines, b=target_lines)
    hunks: list[dict] = []
    for group in matcher.get_grouped_opcodes(context):
        hunk_lines: list[dict] = []
        # group is a list of (tag, i1, i2, j1, j2) opcodes
        source_start = group[0][1]
        target_start = group[0][3]
        source_end = group[-1][2]
        target_end = group[-1][4]
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in source_lines[i1:i2]:
                    hunk_lines.append({"type": "context", "text": line})
            elif tag == "replace":
                for line in source_lines[i1:i2]:
                    hunk_lines.append({"type": "delete", "text": line})
                for line in target_lines[j1:j2]:
                    hunk_lines.append({"type": "insert", "text": line})
            elif tag == "delete":
                for line in source_lines[i1:i2]:
                    hunk_lines.append({"type": "delete", "text": line})
            elif tag == "insert":
                for line in target_lines[j1:j2]:
                    hunk_lines.append({"type": "insert", "text": line})
        hunks.append(
            {
                "source_start": source_start + 1,
                "source_length": max(source_end - source_start, 0),
                "target_start": target_start + 1,
                "target_length": max(target_end - target_start, 0),
                "lines": hunk_lines,
            }
        )
    return hunks


@dataclass(frozen=True)
class _FileDiffEntry:
    path: str
    status: str
    kind: str
    source_hash: str | None
    target_hash: str | None
    hunks: list[dict] | None  # None means binary / not decoded
    binary: bool


def _file_diff_entries(
    source_root: Path,
    target_root: Path,
    source_files: dict[str, str],
    target_files: dict[str, str],
) -> list[_FileDiffEntry]:
    entries: list[_FileDiffEntry] = []
    for path in sorted(set(source_files) | set(target_files)):
        source_hash = source_files.get(path)
        target_hash = target_files.get(path)
        if source_hash == target_hash:
            continue
        if source_hash is None:
            status = "target-only"
        elif target_hash is None:
            status = "source-only"
        else:
            status = "changed"
        kind = _change_kind(path)

        source_path = source_root / path
        target_path = target_root / path
        source_lines = _semantic_text_lines(source_path, path) if source_hash else []
        target_lines = _semantic_text_lines(target_path, path) if target_hash else []
        binary = (source_hash and source_lines is None) or (target_hash and target_lines is None)
        if binary:
            entries.append(
                _FileDiffEntry(
                    path=path,
                    status=status,
                    kind=kind,
                    source_hash=source_hash,
                    target_hash=target_hash,
                    hunks=None,
                    binary=True,
                )
            )
            continue
        hunks = _unified_hunks(source_lines or [], target_lines or [])
        entries.append(
            _FileDiffEntry(
                path=path,
                status=status,
                kind=kind,
                source_hash=source_hash,
                target_hash=target_hash,
                hunks=hunks,
                binary=False,
            )
        )
    return entries


def diff_skill_detailed(
    agentmesh_home: Path,
    name: str,
    target: str,
    home: Path | None = None,
) -> dict:
    """Return a structured, UI-ready diff for a single skill vs a target runtime.

    Shape::

        {
            "skill": "demo-skill",
            "target": "hermes",
            "level": 2,
            "level_name": "CONTENT_CHANGED",
            "summary": "内容不同",
            "files": [
                {
                    "path": "SKILL.md",
                    "status": "changed" | "source-only" | "target-only",
                    "kind": "metadata" | "entrypoint" | "file-tree",
                    "source_hash": "sha256..." | None,
                    "target_hash": "sha256..." | None,
                    "binary": False,
                    "hunks": [ {source_start, source_length,
                                target_start, target_length,
                                lines: [{type: context|delete|insert, text}]} ]
                },
                ...
            ],
            "blocked": False | True,
            "blocked_reasons": ["security", ...],
        }

    This function intentionally reuses the classification of :func:`diff_skill`
    (so the ``level`` / ``level_name`` fields stay in sync with the non-detailed
    API), then attaches per-file unified diff hunks for text files.
    """
    # Top-level classification: mirror diff_skill exactly so the UI badge matches.
    result = diff_skill(agentmesh_home, name, target, home)

    source = resolve_skill_registry_dir(agentmesh_home, name)
    target_path = target_skill_path(name, target, home)

    blocked_reasons: list[str] = []
    detailed_files: list[dict] = []

    if result.level == ConflictLevel.SECURITY_BLOCK:
        blocked_reasons.append("security")
        # Don't emit file-level diffs for secret-blocking findings; return only
        # the change metadata we already computed in diff_skill.
        for change in result.changes or []:
            detailed_files.append(
                {
                    **change,
                    "source_hash": None,
                    "target_hash": None,
                    "binary": False,
                    "hunks": None,
                }
            )
    elif not target_path.exists():
        # Missing target: emit every source file as target-only with full insert hunk.
        source_files = _file_map(source)
        target_files: dict[str, str] = {}
        entries = _file_diff_entries(source, target_path, source_files, target_files)
        detailed_files = [_entry_to_dict(entry) for entry in entries]
    else:
        source_files = _file_map(source)
        target_files = _file_map(target_path)
        entries = _file_diff_entries(source, target_path, source_files, target_files)
        detailed_files = [_entry_to_dict(entry) for entry in entries]

    return {
        "skill": name,
        "target": target,
        "level": int(result.level),
        "level_name": result.name,
        "summary": result.summary,
        "files": detailed_files,
        "blocked": bool(blocked_reasons),
        "blocked_reasons": blocked_reasons,
    }


def _entry_to_dict(entry: _FileDiffEntry) -> dict:
    return {
        "path": entry.path,
        "status": entry.status,
        "kind": entry.kind,
        "source_hash": entry.source_hash,
        "target_hash": entry.target_hash,
        "binary": entry.binary,
        "hunks": entry.hunks,
    }
