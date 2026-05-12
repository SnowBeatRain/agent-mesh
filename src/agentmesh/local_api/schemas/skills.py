"""Skills-related workstation commands.

These are the schemas the workstation uses most heavily. Each schema lists
the parameters the user should be able to tweak in the form, plus the CLI
flags needed to assemble the final command.

Options that depend on runtime state (like "which agents are installed")
use ``options_endpoint="/agents"`` so the front-end pulls them live instead
of hard-coding the list here.
"""

from __future__ import annotations

from agentmesh.local_api.schemas.registry import register_schema
from agentmesh.local_api.schemas.types import CommandSchema, option, param

# Common building-block for any command that takes --registry.
_REGISTRY_PARAM = param(
    name="registry",
    label="Registry 目录",
    type="path",
    required=False,
    help="AgentMesh 工作目录；留空则使用 ~/.agentmesh。",
    cli_flag="--registry",
)


_AGENT_OPTIONS = (
    option("hermes", "Hermes"),
    option("openclaw", "OpenClaw"),
    option("codex", "Codex"),
    option("cursor", "Cursor"),
    option("windsurf", "Windsurf"),
    option("aider", "Aider"),
    option("claude-code", "Claude Code（export-only）"),
)


# ── scan ────────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.scan",
        title="扫描 Agent Skills",
        command="am skills scan",
        description=(
            "扫描本机指定 Agent 下的用户 skills，默认扫描全部 runtime。"
            "仅读取 Agent 的 skill 目录，不写入 registry。"
        ),
        category="skills",
        params=(
            _REGISTRY_PARAM,
            param(
                name="agent",
                label="目标 Agent",
                type="select",
                default="all",
                options=(
                    option("all", "全部 runtime"),
                    option("hermes", "Hermes"),
                    option("openclaw", "OpenClaw"),
                    option("codex", "Codex"),
                    option("cursor", "Cursor"),
                    option("windsurf", "Windsurf"),
                    option("aider", "Aider"),
                    option("claude-code", "Claude Code"),
                ),
                cli_flag="--agent",
                help="选择要扫描的 runtime。Codex 的 .system 始终被排除。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "read"),
    )
)


# ── import ──────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.import",
        title="导入 Skill 到 Registry",
        command="am skills import",
        description=(
            "将指定 Agent 中扫描到的 skills 导入到 AgentMesh registry，生成中立 "
            "manifest 与 provenance。相同内容重复导入是幂等的。"
        ),
        category="skills",
        destructive=False,  # 写入的是 registry，不是目标 runtime
        params=(
            _REGISTRY_PARAM,
            param(
                name="source",
                label="源 Agent",
                type="select",
                required=True,
                options=(
                    option("agent:hermes", "Hermes"),
                    option("agent:openclaw", "OpenClaw"),
                    option("agent:codex", "Codex"),
                    option("agent:cursor", "Cursor"),
                    option("agent:windsurf", "Windsurf"),
                    option("agent:aider", "Aider"),
                    option("agent:claude-code", "Claude Code"),
                    option("agent:all", "全部"),
                ),
                cli_flag="--from",
                help="指定要导入哪个 runtime 的 skills。",
            ),
            param(
                name="dry_run",
                label="仅预览（推荐首次运行时启用）",
                type="boolean",
                default=False,
                cli_flag_when_true="--dry-run",
                cli_flag_when_false="--apply",
            ),
        ),
        tags=("skills", "write"),
    )
)


# ── list ────────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.list",
        title="列出 Registry Skills",
        command="am skills list",
        description=(
            "列出 registry 中的 skills。配合 --detailed 可一次拿到 file_count、"
            "enabled_targets、risk_summary 等字段，适合工作台列表页。"
        ),
        category="skills",
        params=(
            _REGISTRY_PARAM,
            param(
                name="detailed",
                label="返回详细字段",
                type="boolean",
                default=True,
                cli_flag_when_true="--detailed",
                help="JSON 模式下返回 file_count/bytes/source/enabled/risk/last_diff 等。",
            ),
            param(
                name="diff_targets",
                label="Diff 对比目标",
                type="multi-select",
                options=_AGENT_OPTIONS,
                cli_flag="--diff-targets",
                help="配合 --detailed，为每个 skill 计算对各目标的冲突等级。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "read"),
    )
)


# ── show ────────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.show",
        title="查看 Skill 详情",
        command="am skills show",
        description="展示单个 skill 的 manifest、provenance 与风险摘要。",
        category="skills",
        params=(
            param(
                name="name",
                label="Skill 名称",
                type="string",
                required=True,
                help="registry 中的 skill 标识（小写，支持 a-z 0-9 - _）。",
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            _REGISTRY_PARAM,
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "read"),
    )
)


# ── diff ────────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.diff",
        title="Diff Skill 与目标 Runtime",
        command="am skills diff",
        description=(
            "对比 registry 中的 skill 与目标 runtime 中同名 skill 的差异，"
            "输出 conflict level 与变更文件摘要。--target 为必填项。"
        ),
        category="skills",
        params=(
            param(
                name="name",
                label="Skill 名称",
                type="string",
                required=True,
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            _REGISTRY_PARAM,
            param(
                name="target",
                label="目标 Agent",
                type="select",
                required=True,
                options=_AGENT_OPTIONS,
                options_endpoint="/agents",
                cli_flag="--target",
                help="必填。使用 `agentmesh agents list` 查看支持的 agent。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "read", "diff"),
    )
)


# ── enable / disable ────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.enable",
        title="启用 Skill 到目标",
        command="am skills enable",
        description=(
            "在 AgentMesh state 中把 (skill, target) 标记为 enabled。"
            "不会立即写 runtime，需要 `skills sync --enabled --apply` 才落地。"
        ),
        category="skills",
        params=(
            param(
                name="name",
                label="Skill 名称",
                type="string",
                required=True,
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            _REGISTRY_PARAM,
            param(
                name="target",
                label="目标 Agent（可多选）",
                type="multi-select",
                required=True,
                options=_AGENT_OPTIONS,
                cli_flag="--target",
                help="支持逗号分隔，一次启用多个 target。",
            ),
        ),
        tags=("skills", "state"),
    )
)


register_schema(
    CommandSchema(
        id="skills.disable",
        title="禁用 Skill 到目标",
        command="am skills disable",
        description=(
            "在 AgentMesh state 中把 (skill, target) 标记为 disabled。"
            "同样不会删除已同步的 runtime 文件，只影响 enabled sync。"
        ),
        category="skills",
        params=(
            param(
                name="name",
                label="Skill 名称",
                type="string",
                required=True,
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            _REGISTRY_PARAM,
            param(
                name="target",
                label="目标 Agent（可多选）",
                type="multi-select",
                required=True,
                options=_AGENT_OPTIONS,
                cli_flag="--target",
            ),
        ),
        tags=("skills", "state"),
    )
)


# ── status ──────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.status",
        title="查看启用矩阵",
        command="am skills status",
        description=("展示 registry 中每个 skill 的启用状态矩阵。省略 name 时输出全部。"),
        category="skills",
        params=(
            param(
                name="name",
                label="Skill 名称（可选）",
                type="string",
                required=False,
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            _REGISTRY_PARAM,
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "state", "read"),
    )
)


# ── sync ────────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.sync",
        title="同步 Skill 到目标 Runtime",
        command="am skills sync",
        description=(
            "将 registry 中的 skills 同步到一个或多个目标 runtime。默认 dry-run，"
            "显式启用 --apply 且通过安全检查后才真实写入。"
        ),
        category="skills",
        destructive=True,
        confirmation_required=True,
        params=(
            _REGISTRY_PARAM,
            param(
                name="to",
                label="目标 Agent",
                type="multi-select",
                options=_AGENT_OPTIONS,
                cli_flag="--to",
                help=(
                    "支持多选。claude-code 为 export-only，apply 时会被拦截，请改用 skills.export。"
                ),
            ),
            param(
                name="enabled",
                label="使用启用矩阵",
                type="boolean",
                default=False,
                cli_flag_when_true="--enabled",
                help="忽略 --to，按 state 中已启用的 (skill, target) 配对同步。",
            ),
            param(
                name="mode",
                label="同步模式",
                type="select",
                default="copy",
                options=(
                    option("copy", "复制（默认，安全）"),
                    option("symlink", "软链（高级，需 --confirm）"),
                ),
                cli_flag="--mode",
            ),
            param(
                name="dry_run",
                label="仅预览",
                type="boolean",
                default=True,
                cli_flag_when_true="--dry-run",
                cli_flag_when_false="--apply",
                help="强烈推荐先 dry-run，再取消勾选以切换为 --apply。",
            ),
            param(
                name="allow_conflicts",
                label="允许覆盖非安全冲突",
                type="boolean",
                default=False,
                cli_flag_when_true="--allow-conflicts",
                visible_when="dry_run == false",
                help="安全类 block（secret/drift）不会被此开关绕过。",
            ),
            param(
                name="confirm",
                label="确认 symlink 模式",
                type="boolean",
                default=False,
                cli_flag_when_true="--confirm",
                visible_when="mode == 'symlink'",
            ),
            param(
                name="yes",
                label="跳过交互确认",
                type="boolean",
                default=True,
                cli_flag_when_true="--yes",
                visible_when="dry_run == false",
                help="工作台执行时建议保持勾选，由 UI 层提供确认对话框。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "write", "sync"),
    )
)


# ── export / import-package ─────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.export",
        title="导出 Skill Package",
        command="am skills export",
        description=(
            "把 registry 导出为 AgentMesh ZIP package 或 Claude Code plugin package。"
            "用于跨机器分享或 Claude Code 安装前的 sanity check。"
        ),
        category="package",
        params=(
            param(
                name="target",
                label="导出格式",
                type="select",
                required=True,
                default="agentmesh",
                options=(
                    option("agentmesh", "AgentMesh ZIP"),
                    option("claude-code", "Claude Code Plugin"),
                ),
            ),
            _REGISTRY_PARAM,
            param(
                name="out",
                label="输出路径",
                type="path",
                required=True,
                cli_flag="--out",
                help="AgentMesh 目标使用 .zip 文件；Claude Code 目标使用目录。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "package", "write"),
    )
)


register_schema(
    CommandSchema(
        id="skills.import_package",
        title="从 Package 导入",
        command="am skills import-package",
        description=(
            "从 AgentMesh ZIP package 导入 skill 到 registry。默认 dry-run，"
            "显式启用 --apply 才会写入。"
        ),
        category="package",
        destructive=True,
        confirmation_required=True,
        params=(
            param(
                name="package",
                label="Package 路径",
                type="path",
                required=True,
                help="AgentMesh ZIP 文件。",
            ),
            _REGISTRY_PARAM,
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
        tags=("skills", "package", "write"),
    )
)



# ── rename ──────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.rename",
        title="重命名 Skill",
        command="am skills rename",
        description=(
            "在 registry 中重命名一个 skill，同时更新 state/skills.yaml 中的键。"
            "注意：目标 agent 上已同步的副本仍保留旧名字，需额外 sync 或 delete 旧名。"
        ),
        category="skills",
        destructive=True,
        confirmation_required=True,
        params=(
            param(
                name="old_name",
                label="当前名称",
                type="string",
                required=True,
                help="registry 中当前的 skill 名。",
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            param(
                name="new_name",
                label="新名称",
                type="string",
                required=True,
                help="重命名后的 skill 名（小写，支持 a-z 0-9 - _）。",
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            _REGISTRY_PARAM,
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "write", "rename"),
    )
)


# ── delete ──────────────────────────────────────────────────────────────

register_schema(
    CommandSchema(
        id="skills.delete",
        title="删除 Skill",
        command="am skills delete",
        description=(
            "从 registry 中删除一个 skill 及其 state 记录。"
            "可选 --purge-targets 同时清理已同步到各 agent 的副本（仅删除带 lockfile 的目录/链接）。"
        ),
        category="skills",
        destructive=True,
        confirmation_required=True,
        params=(
            param(
                name="name",
                label="Skill 名称",
                type="string",
                required=True,
                help="要删除的 skill 名。",
                validate_regex=r"^[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            _REGISTRY_PARAM,
            param(
                name="purge_targets",
                label="同时清理目标 agent 副本",
                type="boolean",
                default=False,
                cli_flag_when_true="--purge-targets",
                help="删除所有 target runtime 上由 AgentMesh 同步过来的副本。",
            ),
            param(
                name="yes",
                label="跳过交互确认",
                type="boolean",
                default=True,
                cli_flag_when_true="--yes",
                help="工作台执行时建议保持勾选，由 UI 层提供确认对话框。",
            ),
            param(
                name="json_output",
                label="JSON 输出",
                type="boolean",
                default=True,
                cli_flag_when_true="--json",
            ),
        ),
        tags=("skills", "write", "delete"),
    )
)
