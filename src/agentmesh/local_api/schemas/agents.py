"""Agent discovery commands."""

from __future__ import annotations

from agentmesh.local_api.schemas.registry import register_schema
from agentmesh.local_api.schemas.types import CommandSchema, param

register_schema(
    CommandSchema(
        id="agents.list",
        title="列出 Agent Runtime",
        command="am agents list",
        description="列出本机检测到的所有 Agent runtime 及其 skill 目录、模式、能力矩阵。",
        category="agents",
        params=(
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
                help="前端消费 capabilities 矩阵时建议启用。",
            ),
        ),
        tags=("agents", "diagnostics"),
    )
)


register_schema(
    CommandSchema(
        id="agents.contract",
        title="导出 Adapter 契约",
        command="am agents contract",
        description=(
            "输出每个 adapter 的契约声明（protected_paths、safety_guards、writable 等），"
            "便于工作台校验写操作的边界条件。只读命令。"
        ),
        category="agents",
        params=(
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("agents", "contract"),
    )
)
