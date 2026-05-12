from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MemoryAsset:
    """跨 Agent 记忆资产数据模型，schema: agentmesh.memory/v1"""
    agent: str
    name: str
    source_path: Path
    digest: str
    content: str
    format: str  # "markdown" | "yaml" | "json" | "text"
    size: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
