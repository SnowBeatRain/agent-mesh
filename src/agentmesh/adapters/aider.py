from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agentmesh.adapters.base import SkillAdapter
from agentmesh.adapters.common import scan_single_skill_file
from agentmesh.models.runtime import AdapterCapabilities, RuntimeInfo
from agentmesh.models.skill import NativeSkill


class AiderAdapter(SkillAdapter):
    """Adapter for Aider AI pair programming CLI.

    Aider does not have a formal skill/plugin system. It uses:
    - .aider.conf.yml for configuration
    - .aider.conventions.md (or custom path) for coding conventions

    This adapter treats convention files as the closest equivalent to skills.
    It scans for .aider.conventions.md files in common locations.
    """

    name = "aider"

    @property
    def conventions_file(self) -> Path:
        return self.home / ".aider.conventions.md"

    @property
    def config_file(self) -> Path:
        return self.home / ".aider.conf.yml"

    @property
    def skill_dir(self) -> Path:
        # Aider doesn't have a dedicated skill directory;
        # conventions file lives in home
        return self.home

    def detect(self) -> RuntimeInfo:
        installed = self.config_file.exists()
        return RuntimeInfo(
            "aider",
            installed,
            self.conventions_file.parent if self.conventions_file.exists() else self.home,
            "read-write",
            True,
        )

    def scan(self) -> list[NativeSkill]:
        # 单文件 .aider.conventions.md：尝试解析 YAML frontmatter，
        # 没有时回退到静态 "aider-conventions" 名称 + legacy 描述。
        skills = scan_single_skill_file(
            self.name, self.conventions_file, fallback_name="aider-conventions"
        )
        if skills and not skills[0].description:
            skills[0] = replace(skills[0], description="Aider coding conventions")
        return skills

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
                "apply_sync",
                "native_validation",
            ),
            safety_guards=(
                "path_guard",
                "dry_run_default",
                "secret_redaction",
            ),
        )
