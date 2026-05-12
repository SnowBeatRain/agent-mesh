# AgentMesh CLI 参考

`am` 与 `agentmesh` 等价。下面示例优先使用 `am`，也可以替换为 `agentmesh`。

> 当前 CLI 的 `skills sync` 是兼容现有 Agent 的复制式同步。AgentMesh 的长期目标还包括 runtime auto-load：让 Agent 在启动或会话初始化时直接读取 AgentMesh registry 中的共享资产，不必把共享内容重新导出到每个模型/Agent 的私有目录。
>
> 输出原则：内部逻辑可以复杂，但默认输出必须简洁明朗。先说结果，再说影响，最后说下一步；复杂细节进入 `--json`、`--verbose` 或日志。

## 全局

```bash
am --help
am --version
agentmesh --help
agentmesh --version
```

## 初始化与诊断

```bash
am init --registry .tmp-agentmesh
am overview --registry .tmp-agentmesh
am overview --registry .tmp-agentmesh --json
am local status --registry .tmp-agentmesh --json
am local serve --port 9090 --registry .tmp-agentmesh
am doctor --registry .tmp-agentmesh
am agents list
am agents list --json
am agents contract --json
```

说明：

- `init` 创建 AgentMesh home/registry 布局。
- `overview` 是本机轻量总览：汇总 registry、agents、Local API（HTTP server + Dashboard）、Runtime LoadPlan 状态和安全边界。通过 `am local serve` 可启动 HTTP server 在浏览器中查看 Dashboard。
- `local status` 是 `overview` 的 local 子命令别名，适合按"本机状态"语义调用；JSON 使用 `agentmesh.local-status/v1` envelope。所有 Local API handler 返回中已统一应用 path redaction（`_redact_path` 和 `_redact_paths_in_value`），响应值中的用户本地文件路径会被脱敏处理，防止泄露绝对路径信息。非 GET 方法（PUT/PATCH/DELETE/OPTIONS/HEAD）统一返回方法不允许错误 envelope。
- `local serve` 启动 Local API HTTP server（localhost-only read-only）。默认绑定 `127.0.0.1:9090`，浏览器访问 `http://127.0.0.1:9090/` 即可查看 Dashboard UI。支持 `--host` 和 `--port` 参数。Dashboard 在根路径 `/` 和 `/dashboard` 提供，API endpoints（`/health`、`/doctor`、`/agents`、`/overview`、`/skills`、`/history`、`/backups`、`/runtime/status`）返回 JSON，与 `local_api.service` 共享只读 contract。
- `doctor` 检测 Hermes、OpenClaw、Codex、Claude Code 的安装状态、skill 路径和模式，并结合指定 registry 输出诊断。
- `agents list` 只聚焦本机 Agent runtime detection，当前基于用户 home；不要把 `--registry` 理解为 detection root。
- `agents list --json` 使用 `agentmesh.agents-list/v1` envelope，并在每个 agent 条目中包含基础 adapter capabilities matrix 字段：`schema`、`capabilities`、`safety_guards`、`protected_paths`、`mode`、`writable`、`skill_dir`、`installed`、`warnings`。
- `agents contract --json` 使用 `agentmesh.agents-contract/v1` envelope，返回只读 `agentmesh.adapter-contract/v1` 声明；它不启用写操作、不需要网络，`classify` / `render_plan` / `validate_projection` / `audit_hints` 当前仍是 `unsupported`。
- Claude Code 当前以 `export-only` 模式处理，capabilities 包含 `export_package`，并声明 `no_auto_install` safety guard。
- Codex 会提示 `.system 已排除`，JSON 中也会把 `.system` 列为 `protected_paths`，并声明 `exclude_system_skills` safety guard。

## Skills：扫描与导入

```bash
am skills scan --registry .tmp-agentmesh --agent all
am skills scan --registry .tmp-agentmesh --agent hermes --json
am skills import hermes --registry .tmp-agentmesh
```

`--agent` / `import` 的 agent 参数当前支持：

```text
hermes
openclaw
codex
claude-code
all
```

扫描阶段不写 registry 或目标 runtime。导入阶段写入中立 registry：

```text
<registry>/registry/assets/skills/<name>/
```

导入后会生成或保留：

```text
SKILL.md
agentmesh.asset.yaml
agentmesh.skill.yaml
provenance.yaml
references/、scripts/、templates/、assets/ 等目录，如果源 skill 中存在
```

## Skills：列表、重复候选与 Diff

```bash
am skills list --registry .tmp-agentmesh
am skills list --registry .tmp-agentmesh --duplicates
am skills reindex --registry .tmp-agentmesh --json
am skills diff demo-skill --registry .tmp-agentmesh --target hermes
```

当前 `--duplicates` 是基础实现，主要基于 manifest description 找疑似重复候选。`skills reindex --json` 会重建 `<registry>/registry/index/skills.json`，输出 `agentmesh.skills-reindex/v1` envelope，内部 index schema 为 `agentmesh.registry-skills-index/v1`。

当前 `skills diff` 支持 registry skill 与目标 runtime skill 的目录级差异判断：

```text
level 0 IDENTICAL         内容一致
level 1 METADATA_ONLY     仅 manifest 或 SKILL.md frontmatter 等元数据不同
level 2 CONTENT_CHANGED   SKILL.md 正文内容不同
level 3 STRUCTURE_CHANGED 目标 skill 不存在或结构缺失
level 4 MANUAL_REVIEW     references/scripts/templates/assets 等文件树变化，需要人工确认
level 5 SECURITY_BLOCK    来源或目标中发现疑似 secret，输出 redacted
```

当前 `skills diff` / `skills list --conflicts` 已覆盖 manifest、entrypoint 和文件树的基础 diff；更复杂的逐行 diff 展示、合并建议和交互式冲突选择仍在后续阶段。

### 冲突列表

```bash
am skills list --registry .tmp-agentmesh --conflicts --target hermes
am skills list --registry .tmp-agentmesh --conflicts --target hermes --json
```

`--conflicts` 会列出 registry 与目标 runtime 中非 `IDENTICAL` 的 skill。

## Skills：Update 预检

```bash
am skills update-check --registry .tmp-agentmesh
am skills update-check --registry .tmp-agentmesh --json
```

说明：

- `skills update-check` 是 M7 只读预检：不联网、不下载、不读取 token、不写 registry 或 runtime。
- JSON 使用 `agentmesh.update-check/v1` envelope。
- package-sourced skill 会基于本地 `agentmesh.asset.yaml` 的 `source` identity 输出 `unknown`，因为 M7 禁用网络，不能判断是否真的有新版本。
- 没有 source identity 或 source kind 暂不支持的 skill 输出 `skipped`。
- `candidate` 状态预留给后续显式 remote source / 本地可比较源实现；M7 不产生 candidate。

## Skills：验证与导出

```bash
am skills validate --registry .tmp-agentmesh
am skills validate --registry .tmp-agentmesh --json
am skills validate --registry .tmp-agentmesh --native --target hermes --json
am skills export demo-skill --registry .tmp-agentmesh --target claude-code --out .tmp-export
```

说明：

- `skills validate` 会检查 registry 中的 skill manifest / entrypoint / 命名等基础规范。
- `--native` 会调用对应 runtime 的原生命令，例如 Hermes/OpenClaw skills check、Claude plugins validate、Codex skills validate；找不到命令时返回 `skipped`，不是程序失败。
- Claude Code 当前采用 export package，而非直接安装到 `~/.claude/plugins`。

## Skills：同步

```bash
am skills sync --registry .tmp-agentmesh --to hermes,openclaw,codex --dry-run
am skills sync --registry .tmp-agentmesh --to hermes --apply
am skills sync --registry .tmp-agentmesh --to hermes --apply --allow-conflicts
am backup list --registry .tmp-agentmesh
am backup list --registry .tmp-agentmesh --json
am rollback plan <backup-ref> --registry .tmp-agentmesh
am rollback plan <backup-ref> --registry .tmp-agentmesh --json
am rollback apply <backup-ref> --registry .tmp-agentmesh --confirm --json
am history list --registry .tmp-agentmesh
am history list --registry .tmp-agentmesh --json
```

说明：

- 默认建议使用 `--dry-run`。
- 真实写入必须显式 `--apply`。
- `--allow-conflicts` 只允许绕过非安全类内容/文件树冲突，不能绕过 secret/security hard block 或 drift block。
- Codex `.system` 不会被扫描、导入或写入。
- Claude Code 当前是 `export-only`，不作为 `skills sync --apply` 目标。
- `skills sync --apply` 会追加写入 `<registry>/state/sync-history.jsonl`，记录本次计划摘要、actions、targets、sync mode 和 backup 路径。
- `backup list --json` 使用 `agentmesh.backup-list/v1` envelope，把已 apply 的 sync history 投影为 `BackupRecord`；`backup_id` 基于 `sha256(history_id + "\\0" + backup_path)[0:12]` 稳定生成。
- `rollback plan --json` 使用 `agentmesh.rollback-plan-response/v1` CLI envelope，实际 plan 位于 `data.plan`，其 schema 为 `agentmesh.rollback-plan/v1`。`<backup-ref>` 支持 `backup_id`、`history_id` 或 `<registry>/backups/` 内的 backup path；path 解析必须经 `resolve()` 后仍位于 `<registry>/backups/`，否则返回 `unsafe_path` hard block 且不读取该路径。
- `rollback plan` 是只读 plan builder：每次调用都会重新读取 history、backup path 与 live target state，不写 target、不写 backup、不写 lock、不写 history。
- `rollback apply --confirm` 会在写入前复用同一个 builder 重新生成 plan；只有 plan executable、无 hard block 且 action decision 属于 `restore_tree` / `restore_managed_symlink_to_tree` 时才执行。
- `rollback apply --json` 成功时输出 `agentmesh.rollback-apply/v1` envelope，并追加写入 `<registry>/state/rollback-history.jsonl`；restore、lock 或 history 写入失败时会尽力用 `<registry>/backups/rollback-current/` snapshot 恢复 current target。
- rollback target state 包括 `managed_clean`、`managed_drift`、`unmanaged`、`missing`、`backup_missing`、`metadata_missing`、`managed_symlink`、`unsafe_path`；`managed_drift`、`unmanaged`、`unsafe_path` 与 backup 缺失类 hard block 不可通过 CLI 参数绕过。
- symlink rollback 使用独立语义：只允许 AgentMesh 管理的 symlink 进入 `restore_managed_symlink_to_tree` 计划；apply 使用专用 executor，不能用普通 tree restore 悄悄覆盖 unmanaged symlink。
- `history list --json` 使用 `agentmesh.history-list/v1` envelope；当前仍保留历史查看，用于交叉核对 backup 来源。


## Prompts：Target 状态与禁用

```bash
am prompts status --target codex --registry .tmp-agentmesh
am prompts status --target codex --registry .tmp-agentmesh --json
am prompts disable --target codex --registry .tmp-agentmesh --dry-run
am prompts disable --target codex --registry .tmp-agentmesh --apply
am prompts disable --target codex --registry .tmp-agentmesh --apply --json
```

说明：

- `prompts status` 是 M6 只读能力，展示 target live prompt path、是否存在、state 中是否 enabled、当前 enabled prompt、是否由 AgentMesh 管理、live hash 是否 drift；enabled 但缺少 state live hash 时返回 `drift_unknown` / `state-hash-missing`，不误报 clean。
- `prompts status --json` 使用 `agentmesh.prompts-status/v1` envelope，核心数据位于 `data.status`。
- `prompts disable` 默认等价 dry-run，只输出计划；必须显式 `--apply` 才写 state。
- `prompts disable --apply` 会把 target state 标记为 disabled，但不删除 live prompt 文件。
- 如果 live prompt 存在且非空，并且与 state 中记录的 live hash 不一致，`disable --apply` 会先把当前 live 内容回填为 `imported-live-<target>-*` prompt snapshot，并在 target state 中记录 `last_snapshot_prompt`；dry-run 只展示将创建的 snapshot，不写 registry。
- disable 不执行 runtime 写入、不清空 live 文件；后续重新 enable 时仍由 `prompts enable --apply` 接管。

## Package：只读检查与校验

```bash
am package inspect agentmesh-package.zip
am package inspect agentmesh-package.zip --json
am package verify agentmesh-package.zip
am package verify agentmesh-package.zip --json
```

说明：

- `package inspect` 是 M4 只读能力，用于导入前查看 ZIP 内容；不需要 registry。
- `package inspect --json` 使用 `agentmesh.package-inspect/v1` envelope，包含 package schema、skill 数量、文件数量、manifest 摘要、skills 与 files 列表。
- `package verify` 是 M5 只读能力，用于校验 package manifest 中的文件清单与 checksum；不需要 registry、不解包写入、不执行 audit/policy。
- `package verify --json` 使用 `agentmesh.package-verify/v1` envelope，valid package 返回 status `ok`，文件缺失、额外文件或 checksum mismatch 返回 status `error` 且退出码 1。
- 新导出的 `agentmesh.package/v1` 会在 `package.yaml` 中写入 `files[]`，每项包含 `path`、`sha256`、`size`。`package.yaml` 自身不参与 files checksum，避免自引用。
- verify 会阻断 ZIP path traversal、绝对路径、Windows drive path、symlink entry，并对损坏 ZIP、无效 `package.yaml` / 缺少 `package.yaml` 返回 error envelope。
- verify 只证明 package 内容与 manifest 清单一致，不等于 audit / policy 安全审查；导入前仍应运行 `skills import-package --dry-run`。

## Audit

```bash
am audit all --registry .tmp-agentmesh
am audit all --registry .tmp-agentmesh --json
am audit secrets --registry .tmp-agentmesh --json
am audit scripts --registry .tmp-agentmesh --json
am audit platform-refs --registry .tmp-agentmesh --json
```

说明：

- `audit all --json` 使用统一 envelope。
- 具体子命令的 JSON 仍保持兼容旧输出，后续再统一迁移。
- secrets 输出必须 redacted。

## Runtime Bootstrap（含 RuntimeRenderer）

当前 runtime 命令已实现 LoadPlan 生成与 RuntimeRenderer 渲染：

```bash
am runtime load-plan --target openclaw --registry .tmp-agentmesh --json
am runtime env --target openclaw --registry .tmp-agentmesh
am runtime validate --target openclaw --registry .tmp-agentmesh --json
am runtime bootstrap --target openclaw --registry .tmp-agentmesh --dry-run
am runtime bootstrap --target openclaw --registry .tmp-agentmesh --apply --json
am runtime exec-plan --load-plan .tmp-agentmesh/state/runtime-load-plans/openclaw.json --json
am runtime update --target openclaw --registry .tmp-agentmesh --dry-run
am runtime update --target openclaw --registry .tmp-agentmesh --apply --json
am runtime status --target openclaw --registry .tmp-agentmesh --json
am runtime disable --target openclaw --registry .tmp-agentmesh --apply --json
```

说明：

- `runtime update` 重新生成 LoadPlan 并重新渲染 registry skills 为目标 Agent 原生格式。默认为 dry-run，必须显式 `--apply` 才写入。参数：
  - `--target`：目标 runtime（必选）。
  - `--registry`：registry 路径（必选）。
  - `--apply`：执行真实写入；不传则只输出 dry-run 计划。
  - `--json`：以 `agentmesh.runtime-update/v1` envelope 输出。
- `runtime status --json` 返回 `agentmesh.runtime-status/v1` envelope。当 registry 中 skills 文件的修改时间晚于 LoadPlan 的生成时间时，status 会返回 `plan_stale: true` 并显示黄色警告，提示 LoadPlan 已过期，建议运行 `runtime update --apply` 刷新。
- `runtime load-plan --json` 返回 `agentmesh.runtime-load-plan-response/v1` CLI envelope，实际 LoadPlan 位于 `data.plan`；其中包含 `schema: agentmesh.runtime-load-plan/v1`、`plan_id`、`generated_at`、`load_plan_path`、summary 与 skills。该命令会把同一份计划持久化到：

```text
<registry>/state/runtime-load-plans/<target>.json
```

该文件包含 `schema: agentmesh.runtime-load-plan/v1`。`runtime exec-plan` 和生成的 `agentmesh_loader.py` 会校验 schema；schema 不支持、文件不存在或 JSON 损坏时，CLI 会返回 `agentmesh.runtime-exec-plan/v1` error envelope，而不是继续渲染加载动作。

- `runtime bootstrap --apply` 会写入一个轻量 `agentmesh-loader` shim，并调用 RuntimeRenderer 渲染 registry skills 为目标 Agent 原生格式。渲染规则：
  - Hermes / OpenClaw → 合并 SKILL.md
  - Cursor → `.mdc` 规则文件
  - Windsurf → `.md` 规则文件
  - Aider → `conventions.md`
  bootstrap manifest/env 中暴露：

```text
load_plan_path
load_plan_schema: agentmesh.runtime-load-plan/v1
AGENTMESH_LOAD_PLAN
AGENTMESH_LOADER_ENTRYPOINT
```

- shim 中会生成 `agentmesh_loader.py`，用于读取 LoadPlan 并构造 dry-run load/block 动作。
- `runtime exec-plan --load-plan <path> --json` 是本地 dry-run reader：它验证 CLI 可以读取同一份 LoadPlan 并输出 `agentmesh.runtime-exec-plan/v1` envelope。`next_steps` 现已改为动态生成，会根据 LoadPlan 内容包含具体 target 名称和相关操作建议（例如"对 target hermes 运行 runtime bootstrap --apply"），不再使用静态占位文本。
- 当前 `exec-plan` 不执行 `agentmesh_loader.py`，也不注入目标 runtime；它只在 CLI 中读取 LoadPlan 并输出 dry-run actions。生成的 `agentmesh_loader.py` 也有独立执行测试，用于验证 shim reader 本身可读取 `AGENTMESH_LOAD_PLAN`。
- 这些能力仍是 Runtime integration alpha；它证明 shim 能定位并解析 LoadPlan，但不代表目标 Agent 已在真实会话启动时原生加载共享 skill。

- Runtime Audit：`runtime bootstrap --apply` 和 `runtime disable --apply` 操作会自动写入审计日志到：

```text
<registry>/state/runtime-audit/<timestamp>-<operation>.json
```

每条审计记录包含操作类型（`bootstrap` / `disable`）、target、LoadPlan 引用、渲染文件列表和时间戳。

## Prompts：更新与版本历史

```bash
am prompts update <prompt-id> --content-file ./new-prompt.md --registry .tmp-agentmesh
am prompts update <prompt-id> --content-file ./new-prompt.md --name "新名称" --description "新描述" --registry .tmp-agentmesh --json
am prompts versions <prompt-id> --registry .tmp-agentmesh
am prompts versions <prompt-id> --registry .tmp-agentmesh --json
```

说明：

- `prompts update` 更新已有 prompt 的内容、名称或描述，版本号自动递增。`--content-file` 为必选参数，指定新内容文件路径；`--name` 和 `--description` 可选。
- 更新成功后会保留历史版本，旧内容不会被覆盖。
- `prompts update --json` 使用 `agentmesh.prompts-update/v1` envelope，返回更新后的 prompt id、name、version 和 content_hash。
- `prompts versions` 列出指定 prompt 的所有版本历史，包括版本号、内容哈希前缀和创建时间。
- `prompts versions --json` 使用 `agentmesh.prompts-versions/v1` envelope。

## Prompts：多 Target 同步与冲突策略

`prompts enable` 除了 `--target` 单目标外，还支持 `--targets` 和 `--conflict-strategy`：

```bash
am prompts enable <prompt-id> --targets codex,hermes --registry .tmp-agentmesh --dry-run
am prompts enable <prompt-id> --targets codex,hermes --registry .tmp-agentmesh --apply
am prompts enable <prompt-id> --target codex --conflict-strategy backup --registry .tmp-agentmesh --apply
am prompts enable <prompt-id> --target codex --conflict-strategy skip --registry .tmp-agentmesh --apply
am prompts enable <prompt-id> --target codex --conflict-strategy force --registry .tmp-agentmesh --apply
```

说明：

- `--targets` 接受逗号分隔的多个 target 名称，一次将同一 prompt 同步到多个 runtime。
- `--targets` 模式下 JSON 输出使用 `agentmesh.prompts-enable/v1` envelope，`data` 中包含 `plans` 列表（每个 target 一个计划）。
- `--conflict-strategy` 控制当目标已有 live prompt 且内容不一致时的处理方式：
  - `backup`（默认）：先备份现有内容再写入。
  - `skip`：发现冲突时跳过该 target，不写入。
  - `force`：直接覆盖，不备份。
- `--target` 和 `--targets` 至少指定一个，否则报错。

## MemoryMesh：扫描、导入、列表与 Diff

```bash
am memory scan --agent all
am memory scan --agent hermes --json
am memory import hermes --registry .tmp-agentmesh
am memory import hermes --registry .tmp-agentmesh --dry-run
am memory list --registry .tmp-agentmesh
am memory list --registry .tmp-agentmesh --json
am memory diff hermes openclaw --registry .tmp-agentmesh
am memory diff hermes openclaw --name conversation.md --registry .tmp-agentmesh --json
```

说明：

- `memory scan` 扫描各 Agent 的记忆资产文件（如 `conversation.md`、用户偏好等），不写 registry。`--agent` 支持 `hermes`、`openclaw`、`codex`、`claude-code`、`all`。
- `memory scan --json` 使用 `agentmesh.memory-scan/v1` envelope，返回每个资产的 agent、name、source_path、digest、format、size 和 warnings。
- `memory import` 将扫描到的记忆资产导入 registry（写入 `<registry>/memories/`）。默认执行写入，加 `--dry-run` 只预览。
- `memory list` 列出已导入 registry 的记忆资产。`--json` 使用 `agentmesh.memory-list/v1` envelope。
- `memory diff <agent-a> <agent-b>` 比较两个 Agent 的记忆资产差异。可选 `--name` 指定比较特定文件。
- 不带 `--name` 时输出 `only_in_a`、`only_in_b`、`different`、`identical` 分组；带 `--name` 时输出单文件的 level 和 detail。
- `memory diff --json` 使用 `agentmesh.memory-diff/v1` envelope。
- `memory sync --to <agent>` 将 registry 中已导入的记忆同步到目标 Agent。`--dry-run`（默认）预览；`--apply` 实际写入；`--yes` 跳过确认。

## ModelMesh：扫描、Diff、列表与同步

```bash
am model scan --registry .tmp-agentmesh
am model scan --registry .tmp-agentmesh --json
am model diff --registry .tmp-agentmesh
am model diff --registry .tmp-agentmesh --json
am model list --registry .tmp-agentmesh
am model list --registry .tmp-agentmesh --json
```

说明：

- `model scan` 扫描各 Agent 的模型配置（default_model、provider、context_length 等），输出表格。`--json` 使用 `agentmesh.model-scan/v1` envelope。
- `model diff` 比较不同 Agent 之间的模型配置差异（field-level），输出字段名、agent_a/value_a、agent_b/value_b。不足两个 Agent 时提示无差异。`--json` 使用 `agentmesh.model-diff/v1` envelope。
- `model list` 列出各 Agent 的可用模型概览。`--json` 使用 `agentmesh.model-list/v1` envelope，包含 `agents` 列表和 `total` 计数。
- `model scan/diff/list` 为只读操作，不写 registry。
- `model sync --to <agent>` 将模型配置同步到目标 Agent。`--dry-run`（默认）预览；`--apply` 实际写入；`--yes` 跳过确认。

## ToolMesh：扫描、Diff、列表与同步

```bash
am tool scan --registry .tmp-agentmesh
am tool scan --registry .tmp-agentmesh --json
am tool diff --registry .tmp-agentmesh
am tool diff --registry .tmp-agentmesh --json
am tool list --registry .tmp-agentmesh
am tool list --registry .tmp-agentmesh --json
```

说明：

- `tool scan` 扫描各 Agent 的工具配置（profile、tools 列表、disabled_tools），输出表格。`--json` 使用 `agentmesh.tool-scan/v1` envelope。
- `tool diff` 比较不同 Agent 之间的工具配置差异（type、tool_name、agent_a、agent_b）。`--json` 使用 `agentmesh.tool-diff/v1` envelope。
- `tool list` 列出各 Agent 的工具配置概览，包括 profile 信息。`--json` 使用 `agentmesh.tool-list/v1` envelope，包含 `agents` 列表和 `total` 计数。
- `tool scan/diff/list` 为只读操作，不写 registry。
- `tool sync --to <agent>` 将工具配置同步到目标 Agent。`--dry-run`（默认）预览；`--apply` 实际写入；`--yes` 跳过确认。

## Package：发布、安装（含远端）、卸载与列表

```bash
am package publish <skill-name> <version> --registry .tmp-agentmesh
am package publish <skill-name> <version> --registry .tmp-agentmesh --force --json
am package install <skill-name> --registry .tmp-agentmesh
am package install <skill-name> 1.2.0 --registry .tmp-agentmesh --force --resolve-deps --json
am package install https://github.com/user/skill --registry .tmp-agentmesh --yes
am package install https://example.com/skill.zip --registry .tmp-agentmesh --yes
am package install github.com/user/skill --branch dev --registry .tmp-agentmesh --yes
am package uninstall <skill-name> --registry .tmp-agentmesh
am package uninstall <skill-name> --registry .tmp-agentmesh --json
am package list --registry .tmp-agentmesh
am package list --registry .tmp-agentmesh --json
```

说明：

- `package publish` 将 registry 中的 skill 发布为本地 package。版本号需为 semver 格式。`--force` 覆盖已存在的同版本。JSON 使用 `agentmesh.package-publish/v1` envelope。
- `package install` 从本地 package registry 或远端 URL 安装 skill。可选指定版本号，默认安装最新版本。`--force` 覆盖已有同名 skill。`--resolve-deps` 自动解析依赖。支持 GitHub URL（自动 clone/ZIP）、直接 ZIP/tar.gz URL。`--branch` 指定 Git 分支。`--yes` 跳过确认。JSON 使用 `agentmesh.package-install/v1` envelope。已安装且内容相同时 action 为 `skip`。
- `package uninstall` 从 registry 卸载指定 skill。JSON 使用 `agentmesh.package-uninstall/v1` envelope。
- `package list` 列出本地 package registry 中所有已发布的 package，包括 name、latest 版本和所有可用版本。JSON 使用 `agentmesh.package-list/v1` envelope。
- 远端下载包含安全校验：路径穿越防护、zip bomb 检测。

## Runtime：Stale 检测

```bash
am runtime check-stale --target openclaw --registry .tmp-agentmesh
am runtime check-stale --target openclaw --registry .tmp-agentmesh --json
```

说明：

- `runtime check-stale` 是轻量级 LoadPlan 过期检测命令，专为 auto-load hook 脚本设计。
- 它比较当前 registry skills 状态与已持久化的 LoadPlan，判断是否过期（`stale` 或 `fresh`）。
- 过期时会报告具体变化：`skills_added`（新增 skill）、`skills_removed`（移除 skill）、`content_changed`（内容变化）。
- JSON 使用 `agentmesh.runtime-check-stale/v1` envelope，status 为 `stale` 或 `fresh`。
- 非 JSON 模式下，stale 输出黄色警告及变化列表，fresh 输出绿色确认。建议 stale 时运行 `runtime update --target <target> --apply` 刷新。
- 与 `runtime status` 中的 `plan_stale` 字段相比，`check-stale` 更轻量，不加载完整 bootstrap 状态，适合高频调用场景（如 shell hook）。

## 仍未完成 / 路线图

```bash
# 后续方向，不是当前生产级能力
完整 target Agent 原生消费 LoadPlan
云同步、在线 marketplace
远程 package registry（中心化包仓库）
```

当前 Local API 已实现 HTTP server（`am local serve --port 9090`），支持只读 API endpoints 和 Dashboard UI。`local_api/service.py` 提供 `handle_readonly_request()` handler，支持 `GET /health`、`GET /doctor`、`GET /agents`、`GET /overview`、`GET /skills`、`GET /history`、`GET /backups`、`GET /runtime/status`，返回 `agentmesh.local-api-response/v1` envelope，并阻断非 GET 方法。`local_api/server.py` 封装为 HTTP server，默认绑定 `127.0.0.1:9090`，localhost-only。Dashboard 自动在根路径提供。

## 安全约束

- 默认同步为 dry-run；`--apply` 才真实写入。
- Codex `.system` 不会被扫描、导入或写入。
- Claude Code 当前只作为 `export-only` runtime 检测，不自动安装插件。
- 审计和 diff 输出必须 redaction，不泄露疑似密钥正文。
- Runtime bootstrap 不应覆盖用户已有同名 unmanaged loader。
