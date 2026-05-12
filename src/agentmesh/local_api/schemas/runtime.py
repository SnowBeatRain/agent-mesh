"""Runtime Auto-Load schemas.

These wrap the ``runtime`` sub-commands. They are intentionally minimal: the
goal is to let the workstation drive bootstrap / update without cognitively
forcing users into the underlying flag matrix.
"""

from __future__ import annotations

from agentmesh.local_api.schemas.registry import register_schema
from agentmesh.local_api.schemas.types import CommandSchema, option, param

_RUNTIME_TARGET_OPTIONS = (
    option("hermes", "Hermes"),
    option("openclaw", "OpenClaw"),
    option("codex", "Codex"),
)


register_schema(
    CommandSchema(
        id="runtime.status",
        title="Runtime Bootstrap 状态",
        command="am runtime status",
        description="查看指定 runtime 的 bootstrap / LoadPlan 状态。只读。",
        category="runtime",
        params=(
            param(
                name="target",
                label="目标 runtime",
                type="select",
                required=True,
                default="hermes",
                options=_RUNTIME_TARGET_OPTIONS,
                cli_flag="--target",
            ),
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
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("runtime", "read"),
    )
)


register_schema(
    CommandSchema(
        id="runtime.bootstrap",
        title="Runtime Bootstrap",
        command="am runtime bootstrap",
        description=("为目标 runtime 安装 shim / hook。默认 dry-run；启用 --apply 才写入。"),
        category="runtime",
        destructive=True,
        confirmation_required=True,
        params=(
            param(
                name="target",
                label="目标 runtime",
                type="select",
                required=True,
                options=_RUNTIME_TARGET_OPTIONS,
                cli_flag="--target",
            ),
            param(
                name="registry",
                label="Registry 目录",
                type="path",
                required=False,
                cli_flag="--registry",
            ),
            param(
                name="dry_run",
                label="仅预览",
                type="boolean",
                default=True,
                cli_flag_when_true="--dry-run",
                cli_flag_when_false="--apply",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("runtime", "write"),
    )
)
