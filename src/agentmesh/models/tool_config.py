"""ToolMesh 数据模型：统一工具配置 schema。"""

from __future__ import annotations

from dataclasses import dataclass

TOOL_CONFIG_SCHEMA = "agentmesh.tool-config/v1"


@dataclass(frozen=True)
class ToolConfig:
    """统一的工具配置表示（schema: agentmesh.tool-config/v1）。"""

    agent: str
    tools: tuple[str, ...] = ()
    disabled_tools: tuple[str, ...] = ()
    profile: str = ""
    mcp_servers: tuple[str, ...] = ()
    schema: str = TOOL_CONFIG_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "agent": self.agent,
            "tools": list(self.tools),
            "disabled_tools": list(self.disabled_tools),
            "profile": self.profile,
            "mcp_servers": list(self.mcp_servers),
        }


@dataclass(frozen=True)
class ToolDiff:
    """两个 Agent 之间工具配置的差异。"""

    type: str  # "only_in_a", "only_in_b", "enabled_in_a_disabled_in_b", etc.
    tool_name: str
    agent_a: str
    agent_b: str

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "tool_name": self.tool_name,
            "agent_a": self.agent_a,
            "agent_b": self.agent_b,
        }
