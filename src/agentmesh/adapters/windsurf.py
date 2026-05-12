from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agentmesh.adapters.base import SkillAdapter
from agentmesh.adapters.common import scan_flat_skill_files, scan_single_skill_file
from agentmesh.models.runtime import AdapterCapabilities, RuntimeInfo
from agentmesh.models.skill import NativeSkill


class WindsurfAdapter(SkillAdapter):
    """Adapter for Windsurf AI code editor (Codeium).

    Windsurf stores project rules as .windsurfrules (single file, project root)
    or as individual files under .windsurf/rules/. Global rules are managed
    through the editor settings UI.
    """

    name = "windsurf"

    @property
    def skill_dir(self) -> Path:
        return self.home / ".windsurf" / "rules"

    @property
    def legacy_rules_file(self) -> Path:
        return self.home / ".windsurfrules"

    def detect(self) -> RuntimeInfo:
        has_rules = self.skill_dir.exists() or self.legacy_rules_file.exists()
        return RuntimeInfo("windsurf", has_rules, self.skill_dir, "read-write", True)

    def scan(self) -> list[NativeSkill]:
        # .windsurf/rules/ 支持 .md / .txt / 无后缀文件（按 windsurf 官方约定）；
        # frontmatter 不是强制的，但存在时会被解析以提取 name / description。
        # 对无后缀的情况 scan_flat_skill_files 不会接纳（因为 suffixes 过滤），
        # 因此沿用旧实现的显式循环并传给共享的 _build_native_skill。
        skills = scan_flat_skill_files(
            self.name, self.skill_dir, suffixes=(".md", ".txt")
        )
        # legacy .windsurfrules — 没有 frontmatter 约定，保留旧描述。
        legacy = scan_single_skill_file(
            self.name, self.legacy_rules_file, fallback_name="windsurfrules"
        )
        if legacy and not legacy[0].description:
            legacy[0] = replace(legacy[0], description="Legacy Windsurf rules file")
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
