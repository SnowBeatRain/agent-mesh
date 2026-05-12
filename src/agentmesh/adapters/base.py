from abc import ABC, abstractmethod
from pathlib import Path

from agentmesh.config import loader
from agentmesh.models.runtime import (
    AdapterCapabilities,
    AdapterContract,
    RuntimeInfo,
)
from agentmesh.models.skill import NativeSkill


class SkillAdapter(ABC):
    name: str

    def __init__(self, home: Path | None = None):
        self.home = home or loader.user_home()

    @abstractmethod
    def detect(self) -> RuntimeInfo: ...

    @abstractmethod
    def scan(self) -> list[NativeSkill]: ...

    def capabilities(self) -> AdapterCapabilities:
        info = self.detect()
        return AdapterCapabilities(
            name=info.name,
            skill_dir=info.skill_dir,
            mode=info.mode,
            writable=info.writable,
            capabilities=("detect", "scan", "import", "dry_run_sync", "native_validation"),
            safety_guards=("path_guard", "dry_run_default", "secret_redaction"),
        )

    def contract(self) -> AdapterContract:
        caps = self.capabilities()
        return AdapterContract(
            name=caps.name,
            skill_dir=caps.skill_dir,
            mode=caps.mode,
            writable=caps.writable,
            capabilities=caps.capabilities,
            safety_guards=caps.safety_guards,
            protected_paths=caps.protected_paths,
        )
