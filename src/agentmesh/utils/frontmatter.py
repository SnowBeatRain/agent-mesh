from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


@dataclass(frozen=True)
class SkillDocument:
    metadata: dict
    body: str


class FrontmatterError(ValueError):
    """Raised when a SKILL.md frontmatter block cannot be parsed."""


def read_skill_document(path: Path) -> SkillDocument:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return SkillDocument(metadata={}, body=text)
    _, raw_meta, body = text.split("---", 2)
    yaml = YAML(typ="safe")
    try:
        metadata = yaml.load(raw_meta) or {}
    except YAMLError as exc:
        raise FrontmatterError(f"无法解析 SKILL.md frontmatter: {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise FrontmatterError(f"SKILL.md frontmatter 必须是 YAML mapping: {path}")
    return SkillDocument(metadata=metadata, body=body.lstrip("\n"))
