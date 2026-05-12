from pathlib import Path

from agentmesh.adapters.base import SkillAdapter
from agentmesh.adapters.common import scan_skill_dirs
from agentmesh.models.runtime import AdapterCapabilities, RuntimeInfo
from agentmesh.models.skill import NativeSkill


class ClaudeCodeAdapter(SkillAdapter):
    name = "claude-code"

    @property
    def skill_dir(self) -> Path:
        return self.home / ".claude" / "plugins"

    def detect(self) -> RuntimeInfo:
        return RuntimeInfo(
            "claude-code", self.skill_dir.exists(), self.skill_dir, "export-only", False
        )

    def scan(self) -> list[NativeSkill]:
        return scan_skill_dirs(self.name, self.skill_dir)

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            skill_dir=self.skill_dir,
            mode="export-only",
            writable=False,
            capabilities=("detect", "scan", "export_package", "native_validation"),
            safety_guards=("path_guard", "secret_redaction", "no_auto_install"),
        )
