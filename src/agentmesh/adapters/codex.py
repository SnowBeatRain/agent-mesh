from pathlib import Path

from agentmesh.adapters.base import SkillAdapter
from agentmesh.adapters.common import scan_skill_dirs
from agentmesh.models.runtime import AdapterCapabilities, RuntimeInfo
from agentmesh.models.skill import NativeSkill


class CodexAdapter(SkillAdapter):
    name = "codex"

    @property
    def skill_dir(self) -> Path:
        return self.home / ".codex" / "skills"

    def detect(self) -> RuntimeInfo:
        return RuntimeInfo(
            "codex",
            self.skill_dir.exists(),
            self.skill_dir,
            "read-write",
            True,
            (".system 已排除",),
        )

    def scan(self) -> list[NativeSkill]:
        return scan_skill_dirs(self.name, self.skill_dir, skip_system=True)

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
                "runtime_load_plan",
            ),
            safety_guards=(
                "path_guard",
                "dry_run_default",
                "secret_redaction",
                "exclude_system_skills",
            ),
            protected_paths=(".system",),
        )
