"""Backup / rollback command schemas."""

from __future__ import annotations

from agentmesh.local_api.schemas.registry import register_schema
from agentmesh.local_api.schemas.types import CommandSchema, param

register_schema(
    CommandSchema(
        id="backup.list",
        title="列出备份",
        command="am backup list",
        description="列出 AgentMesh home 下的全部备份记录（按 timestamp 排序）。只读。",
        category="rollback",
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
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("rollback", "read"),
    )
)


register_schema(
    CommandSchema(
        id="rollback.plan",
        title="生成 Rollback 计划",
        command="am rollback plan",
        description=(
            "针对指定的 backup-ref 生成回滚计划；只输出计划，不执行。"
            "建议在工作台里先 `backup list` 拿到 backup-ref。"
        ),
        category="rollback",
        params=(
            param(
                name="backup_ref",
                label="Backup 引用",
                type="string",
                required=True,
                help="`backup list` 输出中的 id 或路径。",
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
        tags=("rollback", "read"),
    )
)


register_schema(
    CommandSchema(
        id="rollback.apply",
        title="执行 Rollback",
        command="am rollback apply",
        description=(
            "把目标目录恢复到 backup-ref 所指的状态。必须显式启用 --confirm；"
            "成功后的操作会被记录到 sync 历史。"
        ),
        category="rollback",
        destructive=True,
        confirmation_required=True,
        params=(
            param(
                name="backup_ref",
                label="Backup 引用",
                type="string",
                required=True,
            ),
            param(
                name="registry",
                label="Registry 目录",
                type="path",
                required=False,
                cli_flag="--registry",
            ),
            param(
                name="confirm",
                label="我已理解风险，确认回滚",
                type="boolean",
                default=False,
                required=True,
                cli_flag_when_true="--confirm",
                help="未勾选时命令会直接失败。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("rollback", "write"),
    )
)
