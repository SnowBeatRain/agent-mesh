"""AgentMesh package inspect/verify schemas (read-only).

These commands don't touch the registry; they operate on a standalone ZIP
package. They're exposed here so the workstation can verify a package before
invoking ``skills.import_package``.
"""

from __future__ import annotations

from agentmesh.local_api.schemas.registry import register_schema
from agentmesh.local_api.schemas.types import CommandSchema, param

register_schema(
    CommandSchema(
        id="package.inspect",
        title="检查 Package 清单",
        command="am package inspect",
        description=(
            "快速查看 AgentMesh ZIP package 的 schema、skill/文件数量、"
            "manifest 摘要。不做 audit，不执行 checksum 比对。"
        ),
        category="package",
        params=(
            param(
                name="package",
                label="Package 路径",
                type="path",
                required=True,
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("package", "read"),
    )
)


register_schema(
    CommandSchema(
        id="package.verify",
        title="校验 Package Checksum",
        command="am package verify",
        description=(
            "对 AgentMesh ZIP package 执行完整清单校验：发现缺失、多余文件或内容篡改。导入前必跑。"
        ),
        category="package",
        params=(
            param(
                name="package",
                label="Package 路径",
                type="path",
                required=True,
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("package", "read"),
    )
)
