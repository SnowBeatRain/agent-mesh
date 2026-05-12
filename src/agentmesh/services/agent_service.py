from pathlib import Path

from agentmesh.adapters.aider import AiderAdapter
from agentmesh.adapters.claude_code import ClaudeCodeAdapter
from agentmesh.adapters.codex import CodexAdapter
from agentmesh.adapters.cursor import CursorAdapter
from agentmesh.adapters.hermes import HermesAdapter
from agentmesh.adapters.openclaw import OpenClawAdapter
from agentmesh.adapters.windsurf import WindsurfAdapter
from agentmesh.models.runtime import AdapterCapabilities, RuntimeInfo
from agentmesh.models.skill import NativeSkill

ADAPTERS = {
    "hermes": HermesAdapter,
    "openclaw": OpenClawAdapter,
    "codex": CodexAdapter,
    "claude-code": ClaudeCodeAdapter,
    "cursor": CursorAdapter,
    "windsurf": WindsurfAdapter,
    "aider": AiderAdapter,
}


def get_adapters(home: Path | None = None, agent: str = "all"):
    names = ADAPTERS if agent == "all" else {agent: ADAPTERS[agent]}
    return [cls(home=home) for cls in names.values()]


def detect_agents(home: Path | None = None) -> list[RuntimeInfo]:
    return [adapter.detect() for adapter in get_adapters(home)]


def adapter_capabilities(home: Path | None = None) -> list[AdapterCapabilities]:
    return [adapter.capabilities() for adapter in get_adapters(home)]


def adapter_capabilities_matrix(home: Path | None = None) -> list[dict[str, object]]:
    return [capability.to_dict() for capability in adapter_capabilities(home)]


def adapter_contract_matrix(home: Path | None = None) -> list[dict[str, object]]:
    return [adapter.contract().to_dict() for adapter in get_adapters(home)]


def scan_skills(home: Path | None = None, agent: str = "all") -> list[NativeSkill]:
    skills: list[NativeSkill] = []
    for adapter in get_adapters(home, agent):
        skills.extend(adapter.scan())
    return skills
