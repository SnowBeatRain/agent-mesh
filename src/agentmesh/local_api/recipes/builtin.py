"""Built-in Recipe library.

These are hand-curated workflows matching the six scenarios discussed in
the Phase B plan:

1. ``first-time-setup``    — 从零跑通一次扫描 / 导入 / 审计 / dry-run
2. ``daily-sync``          — 基于 state 启用矩阵的日常同步
3. ``migrate-hermes-to-openclaw`` — 把 Hermes skill 迁移到 OpenClaw
4. ``recover-from-bad-sync`` — 出问题时用 backup / rollback 恢复
5. ``share-via-package``   — 导出 AgentMesh ZIP 给队友
6. ``claude-code-plugin``  — Claude Code 可分发 plugin package 生成

All recipes reference command ids that are registered by
``agentmesh.local_api.schemas``; if a schema id changes, the test
``tests/test_recipes.py::test_every_recipe_step_command_id_is_registered``
will catch the mismatch before the endpoint returns broken data.
"""

from __future__ import annotations

from agentmesh.local_api.recipes.registry import register_recipe
from agentmesh.local_api.recipes.types import Recipe, RecipeStep

# ── 1. First-time setup ────────────────────────────────────────────────

register_recipe(
    Recipe(
        id="first-time-setup",
        title="首次使用：从零跑通 Skills 闭环",
        description=(
            "新安装 AgentMesh 后推荐的 5 分钟上手流程。全部使用临时 registry，"
            "不会改动任何 Agent 的真实 skill 目录。"
        ),
        difficulty="beginner",
        est_minutes=5,
        prerequisites=(
            "已安装 Python 3.10+",
            "至少安装了一个 Agent runtime（Hermes / OpenClaw / Codex 任一即可）",
        ),
        tags=("onboarding", "skills"),
        steps=(
            RecipeStep(
                id=1,
                title="初始化临时 registry",
                command_id="init",
                description="生成 .tmp-agentmesh 目录结构；不会写入系统路径。",
                params_defaults={"registry": ".tmp-agentmesh"},
            ),
            RecipeStep(
                id=2,
                title="环境诊断",
                command_id="doctor",
                description="确认 runtime 检测正常、skill 路径可读。",
                params_defaults={"registry": ".tmp-agentmesh", "json_output": False},
            ),
            RecipeStep(
                id=3,
                title="扫描所有 Agent 的 skills",
                command_id="skills.scan",
                description="只读扫描 7 个 runtime，Codex .system 会被自动排除。",
                params_defaults={
                    "registry": ".tmp-agentmesh",
                    "agent": "all",
                    "json_output": False,
                },
            ),
            RecipeStep(
                id=4,
                title="导入 Hermes skills 到 registry",
                command_id="skills.import",
                description="先 dry-run 看一眼，没问题再重跑时关掉 dry_run 即可。",
                params_defaults={
                    "registry": ".tmp-agentmesh",
                    "source": "agent:hermes",
                    "dry_run": True,
                },
            ),
            RecipeStep(
                id=5,
                title="审计 registry",
                command_id="audit.all",
                description="检测 secrets / 危险脚本 / 平台引用，密钥内容会被 redacted。",
                params_defaults={"registry": ".tmp-agentmesh", "json_output": False},
            ),
            RecipeStep(
                id=6,
                title="同步预览到 OpenClaw",
                command_id="skills.sync",
                description="dry-run 预览同步到 OpenClaw 的计划，不写文件。",
                params_defaults={
                    "registry": ".tmp-agentmesh",
                    "to": ["openclaw"],
                    "dry_run": True,
                    "mode": "copy",
                    "json_output": False,
                },
            ),
        ),
    )
)


# ── 2. Daily sync ──────────────────────────────────────────────────────

register_recipe(
    Recipe(
        id="daily-sync",
        title="日常：增量同步已启用的 skills",
        description=("每天开工前的 15 秒：先看启用矩阵、过审计、dry-run、确认后 apply。"),
        difficulty="intermediate",
        est_minutes=2,
        prerequisites=("Registry 中已导入并启用过至少一个 skill（见 first-time-setup）。",),
        tags=("daily", "skills", "sync"),
        steps=(
            RecipeStep(
                id=1,
                title="查看启用矩阵",
                command_id="skills.status",
                description="确认这次会同步哪些 (skill, target)。",
                params_defaults={"json_output": False},
            ),
            RecipeStep(
                id=2,
                title="审计快照",
                command_id="audit.all",
                description="同步前最后一次只读扫描。",
                params_defaults={"json_output": False},
            ),
            RecipeStep(
                id=3,
                title="Dry-run 同步",
                command_id="skills.sync",
                description=("按启用矩阵预演同步；不会写目标 runtime。"),
                params_defaults={
                    "enabled": True,
                    "dry_run": True,
                    "mode": "copy",
                    "json_output": False,
                    "yes": True,
                },
            ),
            RecipeStep(
                id=4,
                title="正式 apply 同步",
                command_id="skills.sync",
                description=("确认前面的 dry-run 无误后再运行这步；有 backup 与 rollback 兜底。"),
                params_defaults={
                    "enabled": True,
                    "dry_run": False,
                    "mode": "copy",
                    "json_output": False,
                    "yes": True,
                },
                requires_confirm=True,
            ),
        ),
    )
)


# ── 3. Migrate ─────────────────────────────────────────────────────────

register_recipe(
    Recipe(
        id="migrate-hermes-to-openclaw",
        title="迁移：把 Hermes skills 迁移到 OpenClaw",
        description=(
            "从 Hermes 扫描并导入到 registry，然后把 registry 同步给 OpenClaw。"
            "中间走一遍 diff 以便人工确认差异。"
        ),
        difficulty="intermediate",
        est_minutes=6,
        prerequisites=("Hermes 和 OpenClaw 都已安装，且各自有 skill 目录。",),
        tags=("migration", "skills"),
        steps=(
            RecipeStep(
                id=1,
                title="导入 Hermes skills",
                command_id="skills.import",
                params_defaults={"source": "agent:hermes", "dry_run": False},
            ),
            RecipeStep(
                id=2,
                title="列出 registry skills（详细）",
                command_id="skills.list",
                params_defaults={
                    "detailed": True,
                    "diff_targets": ["hermes", "openclaw"],
                    "json_output": False,
                },
            ),
            RecipeStep(
                id=3,
                title="Dry-run 同步到 OpenClaw",
                command_id="skills.sync",
                params_defaults={
                    "to": ["openclaw"],
                    "dry_run": True,
                    "mode": "copy",
                    "json_output": False,
                    "yes": True,
                },
            ),
            RecipeStep(
                id=4,
                title="Apply 同步到 OpenClaw",
                command_id="skills.sync",
                description="确认 dry-run 输出无异常后再运行这步。",
                params_defaults={
                    "to": ["openclaw"],
                    "dry_run": False,
                    "mode": "copy",
                    "json_output": False,
                    "yes": True,
                },
                requires_confirm=True,
            ),
        ),
    )
)


# ── 4. Recover ─────────────────────────────────────────────────────────

register_recipe(
    Recipe(
        id="recover-from-bad-sync",
        title="故障恢复：回滚到上次备份",
        description=(
            "上一次 sync --apply 把目标 runtime 改坏了？用这条 recipe 回滚。"
            "backup list 找到 backup-ref，然后 rollback plan / apply。"
        ),
        difficulty="intermediate",
        est_minutes=3,
        prerequisites=("最近一次 sync --apply 已经产生了 backup 条目。",),
        tags=("rollback", "recover"),
        steps=(
            RecipeStep(
                id=1,
                title="查备份列表",
                command_id="backup.list",
                description="记下你要回滚到的 backup id，粘贴到下一步。",
                params_defaults={"json_output": False},
            ),
            RecipeStep(
                id=2,
                title="生成回滚计划",
                command_id="rollback.plan",
                description="把 backup_ref 填入下方表单；只生成计划不执行。",
                params_defaults={"backup_ref": "", "json_output": False},
            ),
            RecipeStep(
                id=3,
                title="确认并执行回滚",
                command_id="rollback.apply",
                description="请勾选 confirm；回滚记录会进入 sync 历史。",
                params_defaults={"backup_ref": "", "confirm": True, "json_output": False},
                requires_confirm=True,
            ),
        ),
    )
)


# ── 5. Share via package ───────────────────────────────────────────────

register_recipe(
    Recipe(
        id="share-via-package",
        title="分享：导出 AgentMesh ZIP 给队友",
        description=("把 registry 打包成 ZIP，队友收到后可以 inspect / verify / dry-run 导入。"),
        difficulty="beginner",
        est_minutes=3,
        prerequisites=("Registry 中已有要分享的 skills。",),
        tags=("package", "share"),
        steps=(
            RecipeStep(
                id=1,
                title="导出 registry 到 ZIP",
                command_id="skills.export",
                params_defaults={
                    "target": "agentmesh",
                    "out": "./agentmesh-share.zip",
                    "json_output": False,
                },
            ),
            RecipeStep(
                id=2,
                title="自检 package 结构",
                command_id="package.inspect",
                params_defaults={
                    "package": "./agentmesh-share.zip",
                    "json_output": False,
                },
            ),
            RecipeStep(
                id=3,
                title="自检 package checksum",
                command_id="package.verify",
                description="verify 比 inspect 更严格；分享前必跑。",
                params_defaults={
                    "package": "./agentmesh-share.zip",
                    "json_output": False,
                },
            ),
        ),
    )
)


# ── 6. Claude Code plugin ──────────────────────────────────────────────

register_recipe(
    Recipe(
        id="claude-code-plugin",
        title="Claude Code：生成可分发的 plugin package",
        description=(
            "Claude Code 是 export-only，不会自动安装。用这条 recipe 生成 "
            "plugin package，再由用户在 Claude Code 中手动 validate / install。"
        ),
        difficulty="intermediate",
        est_minutes=4,
        prerequisites=("Registry 中已导入并审计过 skills。",),
        tags=("claude-code", "package", "export"),
        steps=(
            RecipeStep(
                id=1,
                title="审计 registry（确认无 block 项）",
                command_id="audit.all",
                params_defaults={"json_output": False},
            ),
            RecipeStep(
                id=2,
                title="导出 Claude Code plugin 目录",
                command_id="skills.export",
                params_defaults={
                    "target": "claude-code",
                    "out": "./.tmp-dist/claude-plugin",
                    "json_output": False,
                },
            ),
            RecipeStep(
                id=3,
                title="提示：下一步请在 Claude Code 中验证",
                command_id="doctor",
                description=(
                    "AgentMesh 不会自动安装 plugin；请到 Claude Code 运行 "
                    "`claude plugins validate ./.tmp-dist/claude-plugin` 验证。"
                    "这一步只是再跑一次 doctor 作为 sanity check。"
                ),
                params_defaults={"json_output": False},
            ),
        ),
    )
)
