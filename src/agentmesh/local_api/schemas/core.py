"""Core workstation commands: init, doctor, overview."""

from __future__ import annotations

from agentmesh.local_api.schemas.registry import register_schema
from agentmesh.local_api.schemas.types import CommandSchema, param

register_schema(
    CommandSchema(
        id="init",
        title="初始化 AgentMesh Registry",
        command="am init",
        description=(
            "在指定目录下建立 AgentMesh 的 registry 目录结构（skills/、backups/、"
            "state/、logs/ 等），并生成默认 config.yaml。首次使用或想要重置到新目录时运行。"
        ),
        category="core",
        destructive=False,
        params=(
            param(
                name="registry",
                label="Registry 目录",
                type="path",
                default=".tmp-agentmesh",
                required=False,
                help="AgentMesh 工作目录；留空则使用 ~/.agentmesh。",
                cli_flag="--registry",
            ),
        ),
        tags=("setup", "getting-started"),
    )
)


register_schema(
    CommandSchema(
        id="doctor",
        title="环境诊断",
        command="am doctor",
        description=(
            "检查本机 Agent runtime 安装情况、runtime bootstrap 状态、rendered "
            "文件是否存在等。用于定位「为何 sync 没效果」之类的基础问题。"
        ),
        category="core",
        params=(
            param(
                name="registry",
                label="Registry 目录",
                type="path",
                required=False,
                help="AgentMesh 工作目录；留空则使用 ~/.agentmesh。",
                cli_flag="--registry",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                help="启用后返回 agentmesh.doctor/v1 信封，方便脚本消费。",
                cli_flag_when_true="--json",
            ),
        ),
        tags=("diagnostics", "getting-started"),
    )
)


register_schema(
    CommandSchema(
        id="overview",
        title="本机总览",
        command="am overview",
        description=(
            "输出 AgentMesh 的本机状态总览：版本、registry 路径、local-first / "
            "dry-run 默认值、Runtime Auto-Load 当前状态、以及各 Agent 的安装/保护情况。"
        ),
        category="core",
        params=(
            param(
                name="registry",
                label="Registry 目录",
                type="path",
                required=False,
                cli_flag="--registry",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("diagnostics",),
    )
)
