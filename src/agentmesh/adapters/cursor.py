from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agentmesh.adapters.base import SkillAdapter
from agentmesh.adapters.common import scan_flat_skill_files, scan_single_skill_file
from agentmesh.models.runtime import AdapterCapabilities, RuntimeInfo
from agentmesh.models.skill import NativeSkill


class CursorAdapter(SkillAdapter):
    """Adapter for Cursor AI code editor.

    Cursor stores project rules as .mdc (Markdown + YAML frontmatter) files
    under .cursor/rules/ within a project directory, or as a legacy single
    .cursorrules file. User-level rules live in ~/.cursor/rules/.

    This adapter scans user-level rules (~/.cursor/rules/) which are
    comparable to the global skill concept in Hermes/OpenClaw.
    """

    name = "cursor"

    @property
    def skill_dir(self) -> Path:
        return self.home / ".cursor" / "rules"

    @property
    def legacy_rules_file(self) -> Path:
        return self.home / ".cursorrules"

    def detect(self) -> RuntimeInfo:
        has_rules = self.skill_dir.exists() or self.legacy_rules_file.exists()
        return RuntimeInfo("cursor", has_rules, self.skill_dir, "read-write", True)

    def scan(self) -> list[NativeSkill]:
        # .cursor/rules/*.mdc 和 *.md：优先采用 YAML frontmatter 声明的
        # name / description；没有 frontmatter 时回退到文件 stem 作为名字。
        skills = scan_flat_skill_files(self.name, self.skill_dir, suffixes=(".mdc", ".md"))
        # legacy 单文件 .cursorrules — 没有 frontmatter 约定，保留旧描述。
        legacy = scan_single_skill_file(
            self.name, self.legacy_rules_file, fallback_name="cursorrules"
        )
        if legacy and not legacy[0].description:
            legacy[0] = replace(legacy[0], description="Legacy Cursor rules file")
        return skills + legacy

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            skill_dir=self.skill_dir,
            mode="read-write",
            writable=True,
            capabilities=(
                "detect",
                "scan",
                "import",
                "dry_run_sync",
                "native_validation",
                "runtime_load_plan",
                "apply_sync",
            ),
            safety_guards=(
                "path_guard",
                "dry_run_default",
                "secret_redaction",
            ),
        )
