from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class NativeSkill:
    name: str
    description: str
    agent: str
    source_path: Path
    entrypoint: Path
    digest: str
    system: bool = False
    generated: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
