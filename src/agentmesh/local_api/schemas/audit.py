"""Audit command schemas."""

from __future__ import annotations

from agentmesh.local_api.schemas.registry import register_schema
from agentmesh.local_api.schemas.types import CommandSchema, option, param

register_schema(
    CommandSchema(
        id="audit.all",
        title="审计 Registry",
        command="am audit all",
        description=(
            "对 registry 中所有 skill 执行静态审计：secrets、危险脚本、平台路径引用。"
            "输出 findings 列表与 policy decision。密钥内容会被 redacted。"
        ),
        category="audit",
        params=(
            param(
                name="registry",
                label="Registry 目录",
                type="path",
                required=False,
                cli_flag="--registry",
            ),
            param(
                name="kinds",
                label="审计类别",
                type="multi-select",
                options=(
                    option("secrets", "Secrets（密钥）"),
                    option("scripts", "危险脚本"),
                    option("platform-refs", "平台引用"),
                ),
                cli_flag="--kinds",
                help="留空表示检测全部类别。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("audit", "read"),
    )
)
